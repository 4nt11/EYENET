"""EYENET Engine — converts observations into Profile snapshots.

M3: per-observation, debounced-by-slot-change profile updates.

On each `actor.observation.text.*` message:
  1. Resolve actor_id from the observation's evidence_ref.
  2. Map the primitive to a Profile slot via slot_mapper.
  3. Build next profile snapshot (increment version, copy summaries, patch slot).
  4. Emit ProfileCandidateEnvelope (always, when a slot is touched).
  5. Evaluate recipes → role_signal + confidence.
  6. If profile materially changed → upsert + emit ProfileCurrentEnvelope + audit.

PLAN §8.4 failure isolation: a failed observation is logged and skipped;
other observations are NOT affected.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import structlog
from behave_text.spec import Observation as ObservationEnvelope
from opentelemetry import trace

from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_PROFILE_CANDIDATE,
    SUBJECT_PROFILE_CURRENT,
    ProfileCandidateEnvelope,
    ProfileCurrentEnvelope,
    ProfileRow,
)
from eyenet.contracts.observation import ObservationRow
from eyenet.service import ServiceBase
from eyenet.telemetry.propagation import current_traceparent

from .recipes import pick_winner
from .slot_mapper import observation_to_slot

_tracer = trace.get_tracer("eyenet.engine")
_log = structlog.get_logger()

_RETRY_DELAY = 0.05  # seconds to wait for sensor/engine race on observation


class Engine(ServiceBase):
    @property
    def name(self) -> str:
        return "engine"

    @property
    def instance_id(self) -> str:
        return "engine_1"

    async def on_subscribe(self) -> None:
        async def _on_obs(subject: str, payload: bytes, headers: dict[str, str]) -> None:
            asyncio.create_task(self._process_observation(subject, payload, headers))  # noqa: RUF006

        async def _on_label(_s: str, _p: bytes, _h: dict[str, str]) -> None:
            _log.info("engine.label_received")

        async def _on_engagement(_s: str, _p: bytes, _h: dict[str, str]) -> None:
            _log.info("engine.engagement_received")

        await self._bus.subscribe("actor.observation.text.>", _on_obs, queue_group="engine")
        await self._bus.subscribe("identity.label.applied", _on_label)
        await self._bus.subscribe("identity.engagement.authorized", _on_engagement)

    async def _process_observation(
        self, subject: str, payload: bytes, _headers: dict[str, str]
    ) -> None:
        try:
            env = ObservationEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("engine.envelope_parse_error", subject=subject, error=str(exc))
            return

        evidence_ref = env.evidence_ref
        if evidence_ref is None:
            _log.debug("engine.observation_no_evidence_ref", primitive=env.primitive)
            return

        obs_store = self._storage.observations

        # Resolve ObservationRow (may race with sensor persistence)
        obs_row: object | None = await obs_store.by_evidence_and_primitive(
            evidence_ref, env.primitive
        )
        if obs_row is None:
            await asyncio.sleep(_RETRY_DELAY)
            obs_row = await obs_store.by_evidence_and_primitive(evidence_ref, env.primitive)
        if obs_row is None:
            _log.warning(
                "engine.observation_row_not_found",
                evidence_ref=evidence_ref,
                primitive=env.primitive,
            )
            return

        row = cast("ObservationRow", obs_row)
        actor_id = row.actor_id

        with _tracer.start_as_current_span(
            "engine.update_profile",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "actor.id": str(actor_id),
                "primitive.name": env.primitive,
                "message.evidence_ref": evidence_ref,
            },
        ) as span:
            try:
                await self._update_profile(actor_id, row, span, envelope_source=env.source)
            except Exception as exc:
                span.record_exception(exc)
                _log.error(
                    "engine.profile_update_error",
                    actor_id=str(actor_id),
                    primitive=env.primitive,
                    error=str(exc),
                )

    async def _update_profile(
        self,
        actor_id: UUID,
        obs_row: ObservationRow,
        _span: object,
        *,
        envelope_source: str | None = None,
    ) -> None:
        mapped = observation_to_slot(obs_row, envelope_source=envelope_source)
        if mapped is None:
            _log.debug(
                "engine.primitive_not_mapped",
                primitive=obs_row.primitive_name,
                actor_id=str(actor_id),
            )
            return

        block_name, slot_key, slot_dict_template = mapped

        profile_store = self._storage.profiles
        raw = await profile_store.get_current(actor_id)
        prev: ProfileRow | None = cast("ProfileRow | None", raw)

        new_profile = _build_next_profile(prev, actor_id, block_name, slot_key, slot_dict_template)

        # Inject the per-slot observation count
        block: dict[str, object] = getattr(new_profile, block_name)
        slot = cast("dict[str, object]", block[slot_key])
        slot["derived_from_observation_count"] = new_profile.derived_from_observation_count

        # Emit candidate (always when a slot is touched)
        await self._emit_candidate(new_profile)

        # Evaluate recipes → role verdict
        winner = pick_winner(new_profile, new_profile.derived_from_observation_count)
        if winner is not None:
            role_signal, role_confidence = winner
            new_profile = new_profile.model_copy(
                update={"role_signal": role_signal, "role_confidence": role_confidence}
            )

        if _materially_differs(prev, new_profile):
            await profile_store.upsert_current(new_profile)
            await self._emit_current(new_profile)
            await self.audit.emit(
                event="profile_current_updated",
                subject_kind="profile",
                payload={
                    "actor_id": str(actor_id),
                    "version": new_profile.version,
                    "role_signal": new_profile.role_signal,
                    "derived_from_observation_count": new_profile.derived_from_observation_count,
                },
            )
            _log.info(
                "engine.profile_updated",
                actor_id=str(actor_id),
                version=new_profile.version,
                role_signal=new_profile.role_signal,
            )

    async def _emit_candidate(self, profile: ProfileRow) -> None:
        tc = _make_trace_context()
        envelope = ProfileCandidateEnvelope(
            trace_context=tc,
            profile_id=profile.id,
            actor_id=profile.actor_id,
            version=profile.version,
            role_signal=profile.role_signal,
            role_confidence=profile.role_confidence,
            derived_at=profile.derived_at,
            derived_from_observation_count=profile.derived_from_observation_count,
        )
        await self.publisher.publish(SUBJECT_PROFILE_CANDIDATE, envelope)

    async def _emit_current(self, profile: ProfileRow) -> None:
        tc = _make_trace_context()
        envelope = ProfileCurrentEnvelope(
            trace_context=tc,
            profile_id=profile.id,
            actor_id=profile.actor_id,
            version=profile.version,
            role_signal=profile.role_signal,
            role_confidence=profile.role_confidence,
            stylometric_summary=profile.stylometric_summary,
            lexical_summary=profile.lexical_summary,
            temporal_summary=profile.temporal_summary,
            interaction_summary=profile.interaction_summary,
            network_summary=profile.network_summary,
            content_summary=profile.content_summary,
            derived_at=profile.derived_at,
            derived_from_observation_count=profile.derived_from_observation_count,
        )
        await self.publisher.publish(SUBJECT_PROFILE_CURRENT, envelope)


def _build_next_profile(
    prev: ProfileRow | None,
    actor_id: UUID,
    block_name: str,
    slot_key: str,
    slot_dict_template: dict[str, object],
) -> ProfileRow:
    """Build a new profile snapshot from the previous one (or blank)."""
    now = datetime.now(tz=UTC)

    if prev is None:
        summaries: dict[str, dict[str, object]] = {
            "stylometric_summary": {},
            "lexical_summary": {},
            "temporal_summary": {},
            "interaction_summary": {},
            "network_summary": {},
            "content_summary": {},
        }
        version = 1
        obs_count = 1
    else:
        summaries = {
            "stylometric_summary": copy.deepcopy(prev.stylometric_summary),
            "lexical_summary": copy.deepcopy(prev.lexical_summary),
            "temporal_summary": copy.deepcopy(prev.temporal_summary),
            "interaction_summary": copy.deepcopy(prev.interaction_summary),
            "network_summary": copy.deepcopy(prev.network_summary),
            "content_summary": copy.deepcopy(prev.content_summary),
        }
        version = prev.version + 1
        obs_count = prev.derived_from_observation_count + 1

    # Patch the slot
    slot_dict = dict(slot_dict_template)
    slot_dict["derived_from_observation_count"] = obs_count
    summaries[block_name][slot_key] = slot_dict

    return ProfileRow(
        id=_new_uuid7(),
        actor_id=actor_id,
        version=version,
        is_current=False,  # upsert_current will flip this
        role_signal=prev.role_signal if prev else None,
        role_confidence=prev.role_confidence if prev else 0.0,
        derived_at=now,
        derived_from_observation_count=obs_count,
        **summaries,
    )


def _materially_differs(prev: ProfileRow | None, new: ProfileRow) -> bool:
    """True if role_signal changed or any summary slot's value changed."""
    if prev is None:
        return True
    if prev.role_signal != new.role_signal:
        return True
    for block_name in (
        "stylometric_summary",
        "lexical_summary",
        "temporal_summary",
        "interaction_summary",
        "network_summary",
        "content_summary",
    ):
        prev_block: dict[str, object] = getattr(prev, block_name)
        new_block: dict[str, object] = getattr(new, block_name)
        for key, new_slot in new_block.items():
            prev_slot = prev_block.get(key)
            if not isinstance(new_slot, dict):
                continue
            prev_value = prev_slot.get("value") if isinstance(prev_slot, dict) else None
            if new_slot.get("value") != prev_value:
                return True
    return False


def _make_trace_context() -> TraceContext:
    tp = current_traceparent()
    if tp is None:
        tp = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"
    return TraceContext(traceparent=tp)


__all__ = ["Engine"]
