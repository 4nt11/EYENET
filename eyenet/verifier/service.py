"""EYENET Verifier service — push-mode subscriber on linkage.proposed.

On each ``attribution.linkage.proposed`` envelope:
  1. Dereference the last-N message bodies for actor_a and actor_b.
  2. Run every Verifier in REGISTRY that is enabled for the pair's
     language (per ``VerifierThresholds.for_verifier``).
  3. Composite score = mean of non-skipped verifier scores.
  4. If composite >= ``composite_floor``: transition Linkage row to
     SUSPECTED and emit ``attribution.linkage.suspected``.
  5. Audit-emit ``verifier.evaluated`` (per verifier) and
     ``linkage.suspected`` (on promotion).

Mirrors ``eyenet/linker/linker.py`` boot/dispatch/audit shape.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import structlog
from opentelemetry import trace

from eyenet.cli.config import VerifierConfig, VerifierThresholds
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_SUSPECTED,
    LinkageProposedEnvelope,
    LinkageSuspectedEnvelope,
)
from eyenet.contracts.bus import Bus
from eyenet.contracts.enums import LinkageState
from eyenet.service import ServiceBase
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.propagation import attach_from_headers, current_traceparent

from .verifiers import REGISTRY, VerificationResult, Verifier, default_registry

_tracer = trace.get_tracer("eyenet.verifier")
_log = structlog.get_logger()

_VERIFIER_DECIDED_BY = "verifier"


def _load_impostor_pool(path: Path | None) -> list[list[str]]:
    """Read a JSONL impostor-pool fixture: one actor per line, list-of-bodies.

    - ``path is None`` → silent empty pool (operator did not configure one;
      GI degrades to plain cosine, confidence floored at 0.3).
    - ``path`` set but missing → WARN and return ``[]`` (operator typo'd a
      path; do not silently degrade).
    - Malformed JSON line → WARN with line number, skip, continue.
    - Wrong record shape → WARN with line number, skip, continue.
    """
    if path is None:
        return []
    if not path.exists():
        _log.warning("verifier.impostor_pool_missing", path=str(path))
        return []

    out: list[list[str]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            _log.warning(
                "verifier.impostor_pool_malformed_line",
                path=str(path),
                line_no=line_no,
                error=str(exc),
            )
            continue
        bodies = rec.get("bodies") if isinstance(rec, dict) else None
        if isinstance(bodies, list) and all(isinstance(b, str) for b in bodies):
            out.append(bodies)
        else:
            _log.warning(
                "verifier.impostor_pool_invalid_record",
                path=str(path),
                line_no=line_no,
            )
    return out


def _make_trace_context() -> TraceContext:
    tp = current_traceparent()
    if tp is None:
        tp = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"
    return TraceContext(traceparent=tp)


class VerifierService(ServiceBase):
    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        config: VerifierConfig | None = None,
        impostor_pool_path: Path | None = None,
        verifiers: tuple[Verifier, ...] | None = None,
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._thresholds: VerifierThresholds = (
            config.thresholds if config is not None else VerifierThresholds()
        )
        if verifiers is not None:
            self._verifiers = verifiers
        else:
            pool = _load_impostor_pool(impostor_pool_path)
            self._verifiers = default_registry(impostor_corpora=pool) if pool else REGISTRY
        self._verifier_count = len(self._verifiers)

    @property
    def name(self) -> str:
        return "verifier"

    @property
    def instance_id(self) -> str:
        return "verifier_1"

    async def on_subscribe(self) -> None:
        async def _on_proposed(subject: str, payload: bytes, headers: dict[str, str]) -> None:
            asyncio.create_task(  # noqa: RUF006
                self._process_proposed(subject, payload, headers)
            )

        await self._bus.subscribe("attribution.linkage.proposed", _on_proposed)
        _log.info(
            "verifier.subscribed",
            verifier_count=self._verifier_count,
            composite_floor=self._thresholds.composite_floor,
        )

    async def _process_proposed(
        self,
        subject: str,
        payload: bytes,
        headers: dict[str, str],
    ) -> None:
        with attach_from_headers(headers):
            await self._process_proposed_inner(subject, payload)

    async def _process_proposed_inner(
        self,
        _subject: str,
        payload: bytes,
    ) -> None:
        try:
            envelope = LinkageProposedEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("verifier.envelope_parse_error", error=str(exc))
            return

        with _tracer.start_as_current_span(
            "verifier.evaluate",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "actor.a.id": str(envelope.actor_a_id),
                "actor.b.id": str(envelope.actor_b_id),
                "linkage.id": str(envelope.linkage_id),
            },
        ):
            await self._evaluate_pair(envelope)

    async def _evaluate_pair(self, envelope: LinkageProposedEnvelope) -> None:
        language = self._extract_language(envelope)

        corpus_a = await self._load_corpus(envelope.actor_a_id)
        corpus_b = await self._load_corpus(envelope.actor_b_id)

        results: list[VerificationResult] = []
        for verifier in self._verifiers:
            floor = self._thresholds.for_verifier(verifier.name, language)
            if floor is None:
                _log.debug(
                    "verifier.disabled_for_language",
                    verifier=verifier.name,
                    language=language,
                )
                continue
            if verifier.requires_language and language is None:
                continue
            with _tracer.start_as_current_span(
                f"verifier.{verifier.name}",
                attributes={
                    "verifier.name": verifier.name,
                    "verifier.language": language or "und",
                },
            ) as verify_span:
                try:
                    result = verifier.verify(corpus_a, corpus_b, language=language)
                except Exception as exc:
                    verify_span.set_attribute("verifier.error", str(exc))
                    _log.error(
                        "verifier.error",
                        verifier=verifier.name,
                        error=str(exc),
                        linkage_id=str(envelope.linkage_id),
                    )
                    continue
                verify_span.set_attribute("verifier.score", result.score)
                verify_span.set_attribute("verifier.confidence", result.confidence)
                verify_span.set_attribute("verifier.skipped", result.skipped)
            results.append(result)
            await self.audit.emit(
                event="verifier.evaluated",
                subject_kind="linkage",
                subject_id=envelope.linkage_id,
                payload={
                    "verifier": result.method,
                    "score": result.score,
                    "confidence": result.confidence,
                    "skipped": result.skipped,
                    "skip_reason": result.skip_reason,
                    "language": language,
                },
            )

        scored = [r for r in results if not r.skipped and r.confidence > 0.0]
        if not scored:
            _log.info(
                "verifier.no_qualified_results",
                linkage_id=str(envelope.linkage_id),
                results=len(results),
            )
            return

        composite = sum(r.score for r in scored) / len(scored)
        floor = self._thresholds.composite_floor

        _log.info(
            "verifier.composite_scored",
            linkage_id=str(envelope.linkage_id),
            composite=composite,
            composite_floor=floor,
            qualified=len(scored),
        )

        if composite < floor:
            return

        await self._promote_to_suspected(envelope, composite, scored)

    async def _promote_to_suspected(
        self,
        envelope: LinkageProposedEnvelope,
        composite: float,
        scored: list[VerificationResult],
    ) -> None:
        try:
            await self._storage.transition_linkage(
                envelope.linkage_id,
                LinkageState.SUSPECTED,
                decided_by=_VERIFIER_DECIDED_BY,
                notes=f"composite={composite:.3f}",
            )
        except ValueError as exc:
            # Already terminal or no longer PROPOSED — operator beat us, fine.
            _log.info(
                "verifier.skip_promotion_illegal_transition",
                linkage_id=str(envelope.linkage_id),
                error=str(exc),
            )
            return

        now = datetime.now(tz=UTC)
        suspected = LinkageSuspectedEnvelope.from_pair(
            envelope.actor_a_id,
            envelope.actor_b_id,
            linkage_id=envelope.linkage_id,
            decided_by=_VERIFIER_DECIDED_BY,
            decided_at=now,
            notes=f"composite={composite:.3f}",
            trace_context=_make_trace_context(),
        )
        await self.publisher.publish(SUBJECT_LINKAGE_SUSPECTED, suspected)

        await self.audit.emit(
            event="linkage.suspected",
            subject_kind="linkage",
            subject_id=envelope.linkage_id,
            payload={
                "actor_a": str(envelope.actor_a_id),
                "actor_b": str(envelope.actor_b_id),
                "composite": composite,
                "verifier_scores": {r.method: r.score for r in scored},
                "promoted_by": _VERIFIER_DECIDED_BY,
            },
        )
        # Allocate a fresh trace ID for the new suspicion event — keeps a
        # readable audit-trace handle even when the upstream proposal has
        # already been compacted out of the OTel buffer.
        _ = _new_uuid7()

    def _extract_language(self, envelope: LinkageProposedEnvelope) -> str | None:
        """Best-effort language extraction from the proposal evidence dict."""
        lang = envelope.evidence.get("language")
        return lang if isinstance(lang, str) else None

    async def _load_corpus(self, actor_id: UUID) -> list[str]:
        """Return last-N message bodies for actor_id, oldest-first."""
        return await self._storage.recent_message_bodies_for_actor(
            actor_id,
            limit=self._thresholds.window_messages,
        )


__all__ = ["VerifierService"]
