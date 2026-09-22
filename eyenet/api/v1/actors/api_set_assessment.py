# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/actors/{actor_id}/assessment — operator free-text assessment.

Analyst-grade dossier note (write:actors). Synchronous: the value is durable on
return, and the write is recorded to the audit chain with the operator's reason.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.schemas.actors import ActorAssessment, SetActorAssessmentRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["actors"])


@router.put(
    "/actors/{actor_id}/assessment",
    operation_id="actors_set_assessment",
    response_model=ActorAssessment,
    status_code=200,
)
async def actors_set_assessment(
    actor_id: UUID,
    body: SetActorAssessmentRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for OpenAPI
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> ActorAssessment:
    updated = await storage.set_actor_assessment(actor_id, body.assessment)
    if not updated:
        raise ResourceNotFound("actor")
    await audit.emit(
        event="eyenet.audit.actor.assessment_set",
        subject_kind="actor",
        subject_id=actor_id,
        system_user_id=current_user.user_id,
        payload={"reason": body.reason},
    )
    return ActorAssessment(actor_id=actor_id, assessment=body.assessment)
