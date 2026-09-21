# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared persona merge/split write path (M9.G4, API_PLAN §4.10a/§10.3).

Operator overrides of the automatic confirmed-linkage merge. The API validates,
audits, writes a ``persona_event_log`` row, and publishes a command
(``attribution.persona.merge`` / ``.split``); the Graph service applies the
actual union-find mutation and emits ``attribution.persona.updated`` (invariant
#2), so ``WriteAccepted.applied`` is False + a poll URL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from eyenet.api.deps import ResourceNotFound, UnprocessableError
from eyenet.api.v1._writes import operator_write
from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_PERSONA_MERGE,
    SUBJECT_PERSONA_SPLIT,
    PersonaMergeCommandEnvelope,
    PersonaSplitCommandEnvelope,
)

if TYPE_CHECKING:
    from eyenet.api.deps import CurrentUser
    from eyenet.api.v1.schemas.personas import PersonaMergeRequest, PersonaSplitRequest
    from eyenet.api.v1.schemas.writes import WriteAccepted
    from eyenet.bus.publisher import BusEnvelopePublisher
    from eyenet.contracts.attribution import PersonaRow
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter


async def merge_personas(
    *,
    persona_id: UUID,
    body: PersonaMergeRequest,
    storage: BaseRepository,
    audit: AuditEmitter,
    publisher: BusEnvelopePublisher,
    current_user: CurrentUser,
) -> WriteAccepted:
    if await storage.get_persona(persona_id) is None:
        raise ResourceNotFound("persona")
    is_self = body.other_persona_id == persona_id
    other_missing = is_self or await storage.get_persona(body.other_persona_id) is None
    if other_missing:
        raise UnprocessableError("other_persona_id must be a distinct, existing persona")
    decided_at = datetime.now(tz=UTC)

    async def _persist(event_id: UUID, traceparent: str) -> None:
        await storage.append_persona_event(
            persona_id=persona_id,
            event_subject=SUBJECT_PERSONA_MERGE,
            event_id=event_id,
            traceparent=traceparent,
            actor=str(current_user.user_id),
        )

    async def _publish(event_id: UUID, traceparent: str) -> None:
        await publisher.publish(
            SUBJECT_PERSONA_MERGE,
            PersonaMergeCommandEnvelope(
                persona_id=persona_id,
                other_persona_id=body.other_persona_id,
                decided_by=current_user.username,
                decided_at=decided_at,
                reason=body.reason,
                case_refs=body.case_refs,
                trace_context=TraceContext(traceparent=traceparent),
            ),
            event_id=event_id,
        )

    return await operator_write(
        audit=audit,
        subject_kind="persona",
        subject_id=persona_id,
        system_user_id=current_user.user_id,
        audit_payload={
            "action": "merge",
            "other_persona_id": str(body.other_persona_id),
            "reason": body.reason,
            "case_refs": body.case_refs,
        },
        subject=SUBJECT_PERSONA_MERGE,
        poll=f"/v1/personas/{persona_id}",
        persist_event=_persist,
        publish_event=_publish,
    )


async def split_persona(
    *,
    persona_id: UUID,
    body: PersonaSplitRequest,
    storage: BaseRepository,
    audit: AuditEmitter,
    publisher: BusEnvelopePublisher,
    current_user: CurrentUser,
) -> WriteAccepted:
    persona_obj = await storage.get_persona(persona_id)
    if persona_obj is None:
        raise ResourceNotFound("persona")
    persona = cast("PersonaRow", persona_obj)
    if body.actor_id not in persona.member_actor_ids:
        raise UnprocessableError("actor_id is not a member of this persona")
    decided_at = datetime.now(tz=UTC)

    async def _persist(event_id: UUID, traceparent: str) -> None:
        await storage.append_persona_event(
            persona_id=persona_id,
            event_subject=SUBJECT_PERSONA_SPLIT,
            event_id=event_id,
            traceparent=traceparent,
            actor=str(current_user.user_id),
        )

    async def _publish(event_id: UUID, traceparent: str) -> None:
        await publisher.publish(
            SUBJECT_PERSONA_SPLIT,
            PersonaSplitCommandEnvelope(
                persona_id=persona_id,
                actor_id=body.actor_id,
                decided_by=current_user.username,
                decided_at=decided_at,
                reason=body.reason,
                case_refs=body.case_refs,
                trace_context=TraceContext(traceparent=traceparent),
            ),
            event_id=event_id,
        )

    return await operator_write(
        audit=audit,
        subject_kind="persona",
        subject_id=persona_id,
        system_user_id=current_user.user_id,
        audit_payload={
            "action": "split",
            "actor_id": str(body.actor_id),
            "reason": body.reason,
            "case_refs": body.case_refs,
        },
        subject=SUBJECT_PERSONA_SPLIT,
        poll=f"/v1/personas/{persona_id}",
        persist_event=_persist,
        publish_event=_publish,
    )


__all__ = ["merge_personas", "split_persona"]
