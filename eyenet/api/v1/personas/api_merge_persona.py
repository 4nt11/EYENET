"""POST /v1/personas/{persona_id}/merge — operator merges another persona in."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1.personas._persona_write import merge_personas
from eyenet.api.v1.schemas.personas import PersonaMergeRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["personas"])


@router.post(
    "/personas/{persona_id}/merge",
    operation_id="personas_merge",
    response_model=WriteAccepted,
    status_code=202,
)
async def personas_merge(
    persona_id: UUID,
    body: PersonaMergeRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:persona_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for the OpenAPI surface
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> WriteAccepted:
    return await merge_personas(
        persona_id=persona_id,
        body=body,
        storage=storage,
        audit=audit,
        publisher=publisher,
        current_user=current_user,
    )
