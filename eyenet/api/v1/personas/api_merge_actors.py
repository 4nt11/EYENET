# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/personas — operator declares two actors the same person (graph menu).

Unlike `/personas/{id}/merge` (persona↔persona), this takes two loose ACTORS and
publishes a `attribution.persona.merge_actors` command; the Graph service (the single
persona writer) union-finds them into a persona and emits `persona.updated`. Audited;
async like the other persona commands (`WriteAccepted.applied` False + poll URL).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    UnprocessableError,
    get_audit,
    get_publisher,
    get_storage,
)
from eyenet.api.v1._writes import operator_write
from eyenet.api.v1.schemas.personas import PersonaMergeActorsRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_PERSONA_MERGE_ACTORS,
    PersonaMergeActorsCommandEnvelope,
)
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["personas"])


@router.post(
    "/personas",
    operation_id="personas_merge_actors",
    response_model=WriteAccepted,
    status_code=202,
)
async def personas_merge_actors(
    body: PersonaMergeActorsRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:persona_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for OpenAPI
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> WriteAccepted:
    if body.actor_a == body.actor_b:
        raise UnprocessableError("actor_a and actor_b must be distinct")
    a_missing = await storage.get_actor(body.actor_a) is None
    b_missing = await storage.get_actor(body.actor_b) is None
    if a_missing or b_missing:
        raise ResourceNotFound("actor")
    decided_at = datetime.now(tz=UTC)

    async def _persist(event_id: UUID, traceparent: str) -> None:  # noqa: ARG001
        return None  # no persona exists yet; the Graph service logs persona.updated

    async def _publish(event_id: UUID, traceparent: str) -> None:
        await publisher.publish(
            SUBJECT_PERSONA_MERGE_ACTORS,
            PersonaMergeActorsCommandEnvelope(
                actor_a=body.actor_a,
                actor_b=body.actor_b,
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
        subject_kind="actor",
        subject_id=body.actor_a,
        system_user_id=current_user.user_id,
        audit_payload={
            "action": "merge_actors",
            "actor_a": str(body.actor_a),
            "actor_b": str(body.actor_b),
            "reason": body.reason,
            "case_refs": body.case_refs,
        },
        subject=SUBJECT_PERSONA_MERGE_ACTORS,
        poll=f"/v1/actors/{body.actor_a}",
        persist_event=_persist,
        publish_event=_publish,
    )
