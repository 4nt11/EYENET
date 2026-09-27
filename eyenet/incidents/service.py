"""IncidentClassifierService — batched incident detection off the message bus.

Subscribes to ``raw.message.>``, buffers arriving envelopes, and flushes a batch when
the buffer reaches ``batch_size`` OR the periodic ``tick()`` fires (``flush_interval``),
whichever comes first. Each flush is exactly THREE round-trips regardless of batch size:
one bulk body fetch, one calibrated ``classify_batch``, one ``put_incidents_bulk``. Only
messages with >=1 fired label are stored (``none`` is the ~majority and is dropped).

Design notes / v1 simplifications (see development/incident-classifier-bus-integration-scope.md):
  - Trace: batching decouples arrival from processing, so the per-message
    ``attach_from_headers`` span model does not hold across a flush. Per-message span
    links are future work; the flush audits each fired detection individually.
  - Inference runs off the event loop in a dedicated single-thread executor, so a flush
    never blocks the bus handler; the pool's one worker serializes inference so
    concurrent flushes cannot race the single CUDA model.
  - Audit: a detection (a fired incident) is the operator-relevant event and is audited;
    routine non-firing scans are not (mass-scan != targeted evidence access).
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from eyenet.contracts._base import TraceContext
from eyenet.contracts.incident import INCIDENT_SUBJECT, IncidentEnvelope, IncidentRow
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.incidents import classifier, rules
from eyenet.service.base import ServiceBase
from eyenet.telemetry import get_logger
from eyenet.telemetry.propagation import ZERO_TRACEPARENT, current_traceparent

_log = get_logger()
_DEFAULT_BATCH = 32
_DEFAULT_FLUSH_S = 1.0
_RULE_REFRESH_S = 30.0  # how often to reload operator rules from storage


class IncidentClassifierService(ServiceBase):
    """Buffered, batched incident classifier service."""

    def __init__(
        self,
        *,
        bus: object,
        storage: object,
        batch_size: int = _DEFAULT_BATCH,
        flush_interval: float = _DEFAULT_FLUSH_S,
    ) -> None:
        super().__init__(bus=bus, storage=storage)  # type: ignore[arg-type]
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._buffer: list[str] = []  # evidence_refs awaiting classification
        self._lock = asyncio.Lock()
        self._model_version = classifier.model_dir().name
        # Inference runs OFF the event loop in a single dedicated thread: torch releases
        # the GIL during compute so the bus handler keeps buffering, and max_workers=1
        # serializes inference so concurrent flushes never race the one CUDA model.
        self._infer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="incident-infer")
        # Operator-defined rules (rules.py), compiled from storage, fired alongside the
        # built-in prefilter. Refreshed periodically so edits go live without a restart.
        self._rules: list[rules.CompiledRule] = []
        self._rules_loaded_at = 0.0

    @property
    def name(self) -> str:
        return "incident_classifier"

    @property
    def instance_id(self) -> str:
        return f"{self.name}_1"

    async def _refresh_rules(self) -> None:
        """Reload + compile enabled operator rules from storage."""
        try:
            rows = await self._storage.list_incident_rules(enabled_only=True)
            self._rules = rules.compile_rules(rows)
            self._rules_loaded_at = time.monotonic()
        except Exception as exc:  # keep the current ruleset on a transient storage error
            _log.warning("incident.rules_refresh_failed", error=str(exc))

    async def _maybe_refresh_rules(self) -> None:
        if time.monotonic() - self._rules_loaded_at >= _RULE_REFRESH_S:
            await self._refresh_rules()

    async def on_subscribe(self) -> None:
        await self._refresh_rules()

        async def _handler(_subject: str, payload: bytes, _headers: dict[str, str]) -> None:
            try:
                env = RawMessageEnvelope.model_validate_json(payload)
            except Exception as exc:  # malformed envelope: log + drop, never crash the bus
                _log.error("incident.envelope_parse_error", error=str(exc))
                return
            async with self._lock:
                self._buffer.append(env.evidence_ref)
                ready = len(self._buffer) >= self._batch_size
            if ready:
                await self._flush()

        await self._bus.subscribe("raw.message.>", _handler, queue_group="incident")

    async def tick(self) -> None:
        """Refresh operator rules if stale, then time-flush so low-traffic messages
        don't wait for a full batch."""
        await self._maybe_refresh_rules()
        await self._flush()

    async def shutdown(self) -> None:
        """Flush any buffered messages, then tear down the inference pool."""
        await self._flush()
        await super().shutdown()
        self._infer_pool.shutdown(wait=False, cancel_futures=True)

    async def _flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            refs = list(dict.fromkeys(self._buffer))  # dedup, preserve arrival order
            self._buffer.clear()

        # Heavy work OUTSIDE the lock so the handler keeps accepting messages.
        by_ref = await self._storage.messages_by_evidence_refs(refs)
        ordered = [(ref, by_ref[ref]) for ref in refs if ref in by_ref]
        if not ordered:
            return
        texts = [body for _, (_mid, body) in ordered]
        loop = asyncio.get_running_loop()
        scored = await loop.run_in_executor(self._infer_pool, classifier.classify_batch, texts)

        now = datetime.now(UTC)
        fired_rows: list[tuple[str, IncidentRow]] = []
        for (ref, (mid, _body)), scores, text in zip(ordered, scored, texts, strict=True):
            fired = (
                {s.label for s in scores if s.fired}
                | classifier.prefilter_labels(text)  # built-in prefilter
                | rules.match_labels(text, self._rules)  # operator rules
            )
            if not fired:
                continue
            row = IncidentRow(
                message_id=mid,
                labels=[s.label for s in scores if s.label in fired],  # head order
                scores={s.label: s.prob for s in scores},
                model_version=self._model_version,
                classified_at=now,
            )
            fired_rows.append((ref, row))
            await self.audit.emit(
                event="incident_detected",
                subject_kind="evidence",
                payload={
                    "evidence_ref": ref,
                    "labels": sorted(fired),
                    "reason": "incident_classification",
                },
            )

        if fired_rows:
            await self._storage.put_incidents_bulk([r for _, r in fired_rows])
            for ref, row in fired_rows:
                await self._publish_incident(ref, row)
        _log.info("incident.flush", scanned=len(ordered), fired=len(fired_rows))

    async def _publish_incident(self, evidence_ref: str, row: IncidentRow) -> None:
        """Emit a fired incident on the bus (triage feed / SSE). Best-effort: a publish
        failure must not lose the stored incident, so it is logged, not raised."""
        try:
            tc = TraceContext(traceparent=current_traceparent() or ZERO_TRACEPARENT)
            await self._publisher.publish(
                INCIDENT_SUBJECT,
                IncidentEnvelope(
                    trace_context=tc,
                    message_id=row.message_id,
                    evidence_ref=evidence_ref,
                    labels=row.labels,
                    scores=row.scores,
                    model_version=row.model_version,
                    classified_at=row.classified_at,
                ),
            )
        except Exception as exc:  # incident is already persisted; feed emit is best-effort
            _log.warning("incident.publish_failed", evidence_ref=evidence_ref, error=str(exc))


__all__ = ["IncidentClassifierService"]
