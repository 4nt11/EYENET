# SPDX-License-Identifier: AGPL-3.0-or-later
"""StealerProcessorService — event-driven ULP processing, running alongside the stack.

Subscribes (queue_group ``stealer`` = horizontal fan-out, plural from day one) to
``stealer.attachment.captured`` and, at boot, replays stealer-marked blobs that were
captured while it was down or marked after capture. For each attachment: recover the
archive password from the promo message body, then decrypt → extract → ulpextract →
ClickHouse (the heavy, subprocess-bound work runs via ``asyncio.to_thread`` so it never
blocks the event loop). Records terminal state so nothing reprocesses; a mid-run crash
leaves no ``done`` row, so the next boot's replay retries it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from eyenet.contracts.group import STEALER_LOG_CATEGORY
from eyenet.contracts.stealer_events import (
    SUBJECT_STEALER_ATTACHMENT_CAPTURED,
    SUBJECT_STEALER_ATTACHMENT_REINDEX,
    SUBJECT_STEALER_ATTACHMENT_REINDEX_URGENT,
    SUBJECT_STEALER_CORPUS_RECLASSIFY,
    SUBJECT_STEALER_CORPUS_REINDEX,
    SUBJECT_STEALER_RULE_REINDEX,
    StealerAttachmentCapturedEnvelope,
    StealerAttachmentReindexEnvelope,
    StealerCorpusReclassifyEnvelope,
    StealerCorpusReindexEnvelope,
    StealerRuleReindexEnvelope,
)
from eyenet.models.stealer import STEALER_DONE, STEALER_FAILED, STEALER_RUNNING
from eyenet.service import ServiceBase
from eyenet.stealer.clickhouse import ClickHouseRecordsSink, FileAuditSink
from eyenet.stealer.gotractor_client import GotractorDaemon
from eyenet.stealer.password import parse_password, password_candidates
from eyenet.stealer.pipeline import process_archive, reindex_archive_by_rules
from eyenet.telemetry.logging import get_logger
from eyenet.telemetry.propagation import attach_from_headers

if TYPE_CHECKING:
    from uuid import UUID

    from eyenet.contracts.bus import Bus
    from eyenet.storage.repository import BaseRepository

_log = get_logger()
# How many unprocessed blobs the boot replay drains (these are heavy multi-GB jobs).
_REPLAY_LIMIT = 1000


class StealerProcessorService(ServiceBase):
    """Turns captured stealer archives into queryable creds, off the bus."""

    def __init__(
        self, *, bus: Bus, storage: BaseRepository, instance_id: str = "stealer_processor_1"
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._instance_id = instance_id
        # file_audit observability side channel. One row per file per
        # archive so operators can SQL-query "what files do we see that
        # we are not parsing".
        self._audit_sink = FileAuditSink()
        # gotractor landing sink: one row per extracted record into
        # stealer.extracted_records (rule-driven, Map(String,String) fields).
        # Set to None via EYENET_STEALER_DISABLE_GOTRACTOR=1 to disable
        # the DSL leg entirely (test fixture / cold-boot path). Rules +
        # families dirs default to the vendored catalog paths; prod
        # overrides via EYENET_STEALER_RULES_DIR / _FAMILIES_DIR.
        _vendored = Path(__file__).parent / "rules" / "catalog"
        _vendored_families = Path(__file__).parent / "families"
        self._rules_dir = Path(os.environ.get("EYENET_STEALER_RULES_DIR", str(_vendored)))
        self._families_dir = Path(
            os.environ.get("EYENET_STEALER_FAMILIES_DIR", str(_vendored_families))
        )
        _gotractor_disabled = os.environ.get("EYENET_STEALER_DISABLE_GOTRACTOR") == "1"
        self._records_sink: ClickHouseRecordsSink | None = (
            None if _gotractor_disabled else ClickHouseRecordsSink()
        )
        # One resident gotractor process per service. Prometheus port is
        # EYENET_GOTRACTOR_METRICS_PORT (default 9091; 0 disables). The
        # subprocess is started in on_subscribe() so test-time service
        # construction doesn't spawn it.
        self._gotractor: GotractorDaemon | None = (
            None
            if _gotractor_disabled
            else GotractorDaemon(
                rules_dir=self._rules_dir,
                families_dir=self._families_dir,
                metrics_port=int(os.environ.get("EYENET_GOTRACTOR_METRICS_PORT", "9091")) or None,
            )
        )
        # Scratch space for the (large) archive extraction; cleaned per-archive.
        self._work_root = Path(
            os.environ.get("EYENET_STEALER_WORK_DIR", "/var/lib/eyenet/stealer-work")
        )
        self._replay_task: asyncio.Task[None] | None = None
        # Serializes process_archive across every path (captured / reindex /
        # corpus / boot-replay). Bus handlers dispatch concurrently via
        # create_task, but the sinks (audit, records) and the single gotractor
        # daemon subprocess are shared singletons that are NOT safe for
        # concurrent use -- two overlapping runs race the one CH client session
        # ("concurrent queries within the same session") and interleave commands
        # on the one gotractor process. The pipeline is single-thread-per-
        # instance by design; this lock enforces it.
        self._process_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "stealer_processor"

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def on_subscribe(self) -> None:
        # v1.3.10: bootstrap schema at service startup, not lazily on first
        # archive. Prior pattern only called records_sink.ensure_schema()
        # from inside _gotractor_insert_daemon (per-archive), which meant
        # new tables/MVs/columns in a release didn't materialize until the
        # next archive actually flowed. On a quiet dev stack or a prod
        # window with no incoming captures, schema drift was invisible.
        # Calling it here is idempotent (every CREATE is IF NOT EXISTS)
        # and runs once at boot.
        if self._records_sink is not None:
            try:
                self._records_sink.ensure_schema()
            except Exception as exc:
                _log.warning("stealer.processor.ensure_schema_failed", error=str(exc))
        if self._gotractor is not None:
            self._gotractor.start()

        async def _on_captured(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process(p, h))  # noqa: RUF006  # fire-and-track below

        async def _on_reindex_one(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process_reindex_event(p, h))  # noqa: RUF006

        async def _on_corpus_reindex(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process_corpus_reindex(p, h))  # noqa: RUF006

        async def _on_corpus_reclassify(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process_corpus_reclassify(p, h))  # noqa: RUF006

        async def _on_rule_reindex(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process_rule_reindex(p, h))  # noqa: RUF006

        await self._bus.subscribe(
            SUBJECT_STEALER_ATTACHMENT_CAPTURED, _on_captured, queue_group="stealer"
        )
        # Operator-driven ops. queue_group matches so horizontal scale still
        # processes each event once; the processor's own subscription group.
        await self._bus.subscribe(
            SUBJECT_STEALER_ATTACHMENT_REINDEX, _on_reindex_one, queue_group="stealer"
        )
        # Urgent per-attachment reindex. Separate queue_group so the fast path
        # never queues behind a corpus sweep; same handler, same envelope.
        await self._bus.subscribe(
            SUBJECT_STEALER_ATTACHMENT_REINDEX_URGENT,
            _on_reindex_one,
            queue_group="stealer_urgent",
        )
        await self._bus.subscribe(
            SUBJECT_STEALER_CORPUS_REINDEX, _on_corpus_reindex, queue_group="stealer"
        )
        await self._bus.subscribe(
            SUBJECT_STEALER_CORPUS_RECLASSIFY, _on_corpus_reclassify, queue_group="stealer"
        )
        await self._bus.subscribe(
            SUBJECT_STEALER_RULE_REINDEX, _on_rule_reindex, queue_group="stealer"
        )
        # Boot replay: archives captured while down, or channels marked after capture.
        self._replay_task = asyncio.create_task(self._replay_unprocessed())

    async def _process(self, payload: bytes, headers: dict[str, str]) -> None:
        # Tracing attach INSIDE the task body (the create_task runs later, §4.5).
        with attach_from_headers(headers):
            try:
                env = StealerAttachmentCapturedEnvelope.model_validate_json(payload)
                await self._process_attachment(env.attachment_id)
            except Exception as exc:
                _log.error("stealer_processor.handler_error", error=str(exc))

    async def _replay_unprocessed(self) -> None:
        try:
            rows = await self._storage.list_unprocessed_stealer_attachments(
                STEALER_LOG_CATEGORY, limit=_REPLAY_LIMIT
            )
        except Exception as exc:
            _log.error("stealer_processor.replay_list_failed", error=str(exc))
            return
        _log.info("stealer_processor.replay", pending=len(rows))
        for att in rows:  # serial — multi-GB extractions; don't stampede disk/CPU
            try:
                await self._process_attachment(att.id)
            except Exception as exc:
                _log.error(
                    "stealer_processor.replay_item_failed", attachment=str(att.id), error=str(exc)
                )

    async def _process_attachment(self, attachment_id: UUID) -> None:
        existing = await self._storage.get_stealer_processing(attachment_id)
        if existing is not None and existing.state == STEALER_DONE:
            return  # idempotent — already ingested
        att = await self._storage.get_attachment(attachment_id)
        if att is None or not att.storage_uri:
            await self._storage.set_stealer_processing(
                attachment_id, state=STEALER_FAILED, error="attachment missing or no blob"
            )
            return
        # Password from the promo message body (self-watermark handle / literal).
        msg = await self._storage.get_message(att.message_id)
        body = getattr(msg, "body", "") or ""
        candidates = password_candidates(parse_password(body))
        # Serialize: the sinks + gotractor daemon are shared singletons; only one
        # extraction may touch them at a time (see self._process_lock).
        async with self._process_lock:
            result = await asyncio.to_thread(
                process_archive,
                blob_path=Path(att.storage_uri),
                password_candidates=candidates,
                work_root=self._work_root,
                source_label=f"attachment:{attachment_id}",
                audit_sink=self._audit_sink,
                records_sink=self._records_sink,
                gotractor=self._gotractor,
            )
        if result.ok:
            # creds_extracted on StealerProcessingTable retains its
            # historical column name; it now stores the gotractor
            # emit count (ulpextract is gone). A migration can rename
            # the column to records_extracted in a follow-up.
            await self._storage.set_stealer_processing(
                attachment_id, state=STEALER_DONE, creds_extracted=result.records_inserted
            )
            _log.info(
                "stealer_processor.done",
                attachment=str(attachment_id),
                records=result.records_inserted,
                gotractor_families=result.gotractor_families,
                password_used=bool(result.password_used),
            )
        else:
            await self._storage.set_stealer_processing(
                attachment_id, state=STEALER_FAILED, error=result.error
            )
            _log.warning(
                "stealer_processor.failed", attachment=str(attachment_id), error=result.error
            )

    async def _process_reindex_event(self, payload: bytes, headers: dict[str, str]) -> None:
        with attach_from_headers(headers):
            try:
                env = StealerAttachmentReindexEnvelope.model_validate_json(payload)
                _log.info(
                    "stealer_processor.reindex_one",
                    attachment=str(env.attachment_id),
                    requested_by=str(env.requested_by) if env.requested_by else "",
                )
                # Clear the processing state so _process_attachment
                # does not short-circuit on "already done" - operator
                # asked for a rerun.
                await self._storage.set_stealer_processing(
                    env.attachment_id, state=STEALER_RUNNING, error=None
                )
                await self._process_attachment(env.attachment_id)
            except Exception as exc:
                _log.error("stealer_processor.reindex_one_failed", error=str(exc))

    async def _process_corpus_reindex(self, payload: bytes, headers: dict[str, str]) -> None:
        with attach_from_headers(headers):
            try:
                env = StealerCorpusReindexEnvelope.model_validate_json(payload)
                limit = env.limit if env.limit > 0 else _REPLAY_LIMIT
                _log.info(
                    "stealer_processor.corpus_reindex_start",
                    limit=limit,
                    requested_by=str(env.requested_by) if env.requested_by else "",
                )
                rows = await self._storage.list_stealer_attachments_for_reindex(
                    STEALER_LOG_CATEGORY, limit=limit
                )
                for att in rows:
                    try:
                        if not env.resume:
                            # Full replay (from-zero rebuild): force RUNNING so the
                            # STEALER_DONE idempotency guard in _process_attachment is
                            # defeated and every archive is re-extracted.
                            await self._storage.set_stealer_processing(
                                att.id, state=STEALER_RUNNING, error=None
                            )
                        # Resume: leave state untouched -- _process_attachment returns
                        # early on STEALER_DONE, so only not-done (pending / failed /
                        # the one RUNNING at the crash) attachments are processed. The
                        # per-attachment state is the cursor; no restore file needed.
                        await self._process_attachment(att.id)
                    except Exception as exc:
                        _log.error(
                            "stealer_processor.corpus_reindex_item_failed",
                            attachment=str(att.id),
                            error=str(exc),
                        )
                _log.info(
                    "stealer_processor.corpus_reindex_done",
                    processed=len(rows),
                    resume=env.resume,
                )
            except Exception as exc:
                _log.error("stealer_processor.corpus_reindex_failed", error=str(exc))

    async def _process_corpus_reclassify(self, payload: bytes, headers: dict[str, str]) -> None:
        """Re-score every (archive, victim) pair under the current family
        catalog without re-extracting. Cheap compared to reindex; writes
        verdicts to victim_family_verdict via the same path pipeline.py
        uses on each archive."""
        with attach_from_headers(headers):
            try:
                env = StealerCorpusReclassifyEnvelope.model_validate_json(payload)
                _log.info(
                    "stealer_processor.corpus_reclassify_start",
                    requested_by=str(env.requested_by) if env.requested_by else "",
                )
                count = await asyncio.to_thread(_run_corpus_reclassify)
                _log.info("stealer_processor.corpus_reclassify_done", victims=count)
            except Exception as exc:
                _log.error("stealer_processor.corpus_reclassify_failed", error=str(exc))

    def _rule_path_globs(self, rule_ids: list[str]) -> list[str]:
        """Read the rule catalog YAMLs and return the path_globs for the given
        rule ids. Used to decide which archive members a rule-reindex extracts.
        rules_dir is operator config, not user input."""
        import yaml  # noqa: PLC0415

        wanted = set(rule_ids)
        globs: list[str] = []
        for yf in sorted(self._rules_dir.glob("*.yaml")):
            try:
                doc = yaml.safe_load(yf.read_text(encoding="utf-8"))
            except Exception as exc:
                _log.warning(
                    "stealer_processor.rule_glob_parse_failed", file=str(yf), error=str(exc)
                )
                continue
            if isinstance(doc, dict) and doc.get("id") in wanted:
                globs.append(str(doc.get("path_glob", "**/*")))
        return globs

    async def _process_rule_reindex(self, payload: bytes, headers: dict[str, str]) -> None:
        """Reindex-by-rule: re-extract only env.rule_ids across the corpus by
        per-member-extracting just the files matching their path_globs (RAR) and
        running gotractor with the rule subset. Cheap backfill for a new/fixed
        rule; dedup-safe, other rules untouched."""
        with attach_from_headers(headers):
            try:
                env = StealerRuleReindexEnvelope.model_validate_json(payload)
                path_globs = self._rule_path_globs(env.rule_ids)
                if not path_globs:
                    _log.warning("stealer_processor.rule_reindex_no_globs", rule_ids=env.rule_ids)
                    return
                if self._gotractor is None:
                    _log.error("stealer_processor.rule_reindex_no_gotractor")
                    return
                limit = env.limit if env.limit > 0 else _REPLAY_LIMIT
                _log.info(
                    "stealer_processor.rule_reindex_start",
                    rule_ids=env.rule_ids,
                    path_globs=path_globs,
                    limit=limit,
                )
                rows = await self._storage.list_stealer_attachments_for_reindex(
                    STEALER_LOG_CATEGORY, limit=limit
                )
                touched = 0
                for att in rows:
                    if not att.storage_uri:
                        continue
                    try:
                        msg = await self._storage.get_message(att.message_id)
                        body = getattr(msg, "body", "") or ""
                        candidates = password_candidates(parse_password(body))
                        # Shared gotractor daemon + sinks -> serialize (see lock).
                        async with self._process_lock:
                            res = await asyncio.to_thread(
                                reindex_archive_by_rules,
                                blob_path=Path(att.storage_uri),
                                password_candidates=candidates,
                                rule_ids=env.rule_ids,
                                path_globs=path_globs,
                                work_root=self._work_root,
                                source_label=f"attachment:{att.id}",
                                gotractor=self._gotractor,
                            )
                        if res.matched_files:
                            touched += 1
                    except Exception as exc:
                        _log.error(
                            "stealer_processor.rule_reindex_item_failed",
                            attachment=str(att.id),
                            error=str(exc),
                        )
                _log.info(
                    "stealer_processor.rule_reindex_done",
                    rule_ids=env.rule_ids,
                    archives_touched=touched,
                    scanned=len(rows),
                )
            except Exception as exc:
                _log.error("stealer_processor.rule_reindex_failed", error=str(exc))

    async def shutdown(self) -> None:
        self._audit_sink.close()
        if self._records_sink is not None:
            self._records_sink.close()
        if self._gotractor is not None:
            self._gotractor.close()
        await super().shutdown()


def _run_corpus_reclassify() -> int:
    """Sync helper: sweep every (archive, victim) pair and write a
    verdict row. Mirrors the stealer-reclassify CLI body. Isolated so
    the async service can off-load to a thread."""
    from eyenet.stealer.classifier import classify  # noqa: PLC0415
    from eyenet.stealer.classifier_io import (  # noqa: PLC0415
        collect_evidence_sync,
        write_verdict_sync,
    )
    from eyenet.stealer.clickhouse import (  # noqa: PLC0415
        FileAuditSink,
        clickhouse_db,
        get_clickhouse_client,
    )

    client = get_clickhouse_client()
    db = clickhouse_db()
    FileAuditSink().ensure_schema()
    # v1.3.5: dropped FINAL; see classifier_io.py.
    rows = client.query(
        "SELECT DISTINCT archive_sha256, victim_folder "  # noqa: S608  # nosec B608
        f"FROM {db}.file_audit "
        "WHERE victim_folder != '' "
        "ORDER BY archive_sha256, victim_folder"
    ).result_rows
    processed = 0
    for sha, vf in rows:
        sha_s = sha.decode("ascii") if isinstance(sha, bytes) else str(sha)
        vf_s = str(vf)
        try:
            ev = collect_evidence_sync(client, sha_s, vf_s)
            result = classify(ev)
            write_verdict_sync(client, sha_s, vf_s, result)
            processed += 1
        except Exception as exc:
            _log.warning(
                "stealer.corpus_reclassify.victim_failed",
                archive=sha_s,
                victim=vf_s,
                error=str(exc),
            )
    return processed


__all__ = ["StealerProcessorService"]
