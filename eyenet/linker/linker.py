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
from eyenet.telemetry.propagation import current_traceparent

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
        _subject: str,
        payload: bytes,
        _headers: dict[str, str],
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

        threshold = self._thresholds.for_comparator(comparator.name)

        await self._storage.vector_index.upsert_simhash(actor_id, comparator.primitive_name, value)

        matches: list[VectorMatch] = await self._storage.vector_index.nearest(
            comparator.primitive_name,
            value,
            max_distance=threshold,
            exclude_actor_id=actor_id,
        )

        for match in matches:
            result = comparator.compare(value, match.simhash_hex, threshold)
            await self._emit_proposal(envelope, match.actor_id, comparator.name, result)

    async def _emit_proposal(
        self,
        envelope: ProfileCurrentEnvelope,
        other_actor_id: UUID,
        method: str,
        result: ComparisonResult,
    ) -> None:
        linkage_id = _new_uuid7()
        now = datetime.now(tz=UTC)
        tc = _make_trace_context()

        proposed_env = LinkageProposedEnvelope.from_pair(
            envelope.actor_id,
            other_actor_id,
            linkage_id=linkage_id,
            method=method,
            score=result.score,
            evidence=dict(result.evidence),
            proposed_at=now,
            trace_context=tc,
        )

        await self.publisher.publish(SUBJECT_LINKAGE_PROPOSED, proposed_env)

        await self._storage.linkages.insert_proposed(
            actor_a=envelope.actor_id,
            actor_b=other_actor_id,
            method=method,
            score=result.score,
            evidence=dict(result.evidence),
        )

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
