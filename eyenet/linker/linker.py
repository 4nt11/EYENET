"""EYENET Linker — computes cross-actor Hamming distance and proposes linkages.

On each `attribution.profile.current` message:
  1. Parse ProfileCurrentEnvelope.
  2. For each comparator in REGISTRY:
     a. Extract slot value from envelope; skip if absent.
     b. Upsert simhash into VectorIndex.
     c. Query nearest neighbors within threshold (returns VectorMatch with neighbor hex).
     d. For each match: call comparator.compare, emit LinkageProposedEnvelope, persist.
  3. Audit-emit `linkage.proposed` per new proposal.

PLAN §8.3 tracing: one `linker.compare` span per incoming envelope.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import structlog
from opentelemetry import trace

from eyenet.cli.config import LinkerConfig, LinkerThresholds
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_PROPOSED,
    LinkageProposedEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.contracts.bus import Bus
from eyenet.service import ServiceBase
from eyenet.storage.sqlite import SQLiteStorage
from eyenet.storage.vectors import VectorMatch
from eyenet.telemetry.propagation import attach_from_headers, current_traceparent

from .comparators import REGISTRY, Comparator, ComparisonResult

_tracer = trace.get_tracer("eyenet.linker")
_log = structlog.get_logger()


class Linker(ServiceBase):
    def __init__(
        self,
        *,
        bus: Bus,
        storage: SQLiteStorage,
        config: LinkerConfig | None = None,
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._thresholds: LinkerThresholds = (
            config.thresholds if config is not None else LinkerThresholds()
        )

    @property
    def name(self) -> str:
        return "linker"

    @property
    def instance_id(self) -> str:
        return "linker_1"

    async def on_subscribe(self) -> None:
        async def _on_profile(subject: str, payload: bytes, headers: dict[str, str]) -> None:
            asyncio.create_task(  # noqa: RUF006
                self._process_profile(subject, payload, headers)
            )

        await self._bus.subscribe("attribution.profile.current", _on_profile)

    async def _process_profile(
        self,
        subject: str,
        payload: bytes,
        headers: dict[str, str],
    ) -> None:
        with attach_from_headers(headers):
            await self._process_profile_inner(subject, payload)

    async def _process_profile_inner(
        self,
        _subject: str,
        payload: bytes,
    ) -> None:
        try:
            envelope = ProfileCurrentEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("linker.envelope_parse_error", error=str(exc))
            return

        with _tracer.start_as_current_span(
            "linker.compare",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "actor.a.id": str(envelope.actor_id),
            },
        ):
            for comparator in REGISTRY:
                try:
                    await self._run_comparator(envelope, comparator)
                except Exception as exc:
                    _log.error(
                        "linker.comparator_error",
                        comparator=comparator.name,
                        error=str(exc),
                    )

    async def _run_comparator(
        self,
        envelope: ProfileCurrentEnvelope,
        comparator: Comparator,
    ) -> None:
        actor_id = envelope.actor_id
        value = comparator.slot_value(envelope)
        if value is None:
            _log.debug(
                "linker.slot_absent",
                actor_id=str(actor_id),
                slot_path=comparator.slot_path,
            )
            return

        slot_lang = comparator.slot_language(envelope)
        threshold = self._thresholds.for_comparator(comparator.name, slot_lang)

        # Per-language disable sentinel (PLAN §M5 / Rutify 2026-05-22):
        # the comparator was explicitly disabled for this actor's language
        # because the primitive is empirically uninformative on this
        # language/domain combo. Skip the VectorIndex round-trip entirely.
        if threshold is None:
            _log.debug(
                "linker.comparator_disabled_for_language",
                comparator=comparator.name,
                language=slot_lang,
                actor_id=str(actor_id),
            )
            return

        await self._storage.vector_index.upsert_simhash(actor_id, comparator.primitive_name, value)

        matches: list[VectorMatch] = await self._storage.vector_index.nearest(
            comparator.primitive_name,
            value,
            max_distance=threshold,
            exclude_actor_id=actor_id,
        )

        for match in matches:
            result = comparator.compare(value, match.simhash_hex, threshold)
            await self._emit_proposal(
                envelope, match.actor_id, comparator.name, result, language=slot_lang
            )

    async def _emit_proposal(
        self,
        envelope: ProfileCurrentEnvelope,
        other_actor_id: UUID,
        method: str,
        result: ComparisonResult,
        *,
        language: str | None,
    ) -> None:
        linkage_id = _new_uuid7()
        now = datetime.now(tz=UTC)
        tc = _make_trace_context()

        # M8: propagate the actor's detected language into the proposal
        # evidence so the Verifier (and any other downstream consumer) can
        # apply per-language behavior without re-reading ProfileCurrent.
        # The Comparator's evidence is merged first; we add language last
        # so a comparator can't accidentally shadow this key.
        evidence: dict[str, object] = dict(result.evidence)
        if language is not None:
            evidence["language"] = language

        proposed_env = LinkageProposedEnvelope.from_pair(
            envelope.actor_id,
            other_actor_id,
            linkage_id=linkage_id,
            method=method,
            score=result.score,
            evidence=evidence,
            proposed_at=now,
            trace_context=tc,
        )

        # Persist BEFORE publishing — downstream subscribers (e.g. M8
        # Verifier) transition the row by linkage_id and need it visible
        # by the time they read the bus message. The opposite order races
        # on real NATS.
        await self._storage.linkages.insert_proposed(
            actor_a=envelope.actor_id,
            actor_b=other_actor_id,
            method=method,
            score=result.score,
            evidence=evidence,
            linkage_id=linkage_id,
        )

        await self.publisher.publish(SUBJECT_LINKAGE_PROPOSED, proposed_env)

        await self.audit.emit(
            event="linkage.proposed",
            subject_kind="linkage",
            subject_id=linkage_id,
            payload={
                "actor_a": str(envelope.actor_id),
                "actor_b": str(other_actor_id),
                "method": method,
                "score": result.score,
                "distance": result.distance,
            },
        )

        _log.info(
            "linker.linkage_proposed",
            actor_a=str(envelope.actor_id),
            actor_b=str(other_actor_id),
            method=method,
            score=result.score,
            distance=result.distance,
        )


def _make_trace_context() -> TraceContext:
    tp = current_traceparent()
    if tp is None:
        tp = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"
    return TraceContext(traceparent=tp)


__all__ = ["Linker"]
