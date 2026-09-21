"""POST /v1/linkages/{linkage_id}/confirm — operator decision: CONFIRMED."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    get_audit,
    get_publisher,
    get_storage,
)
from eyenet.api.v1.linkages._decide import decide_linkage
from eyenet.api.v1.schemas.linkages import LinkageDecisionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.attribution import SUBJECT_LINKAGE_CONFIRMED, LinkageConfirmedEnvelope
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["linkages"])


@router.post(
    "/linkages/{linkage_id}/confirm",
    operation_id="linkages_confirm",
    response_model=WriteAccepted,
    status_code=202,
)
async def linkages_confirm(
    linkage_id: UUID,
    body: LinkageDecisionRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:linkage_decision"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for the OpenAPI surface
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> WriteAccepted:
    return await decide_linkage(
        linkage_id=linkage_id,
        body=body,
        decision="confirmed",
        subject=SUBJECT_LINKAGE_CONFIRMED,
        envelope_cls=LinkageConfirmedEnvelope,
        storage=storage,
        audit=audit,
        publisher=publisher,
        current_user=current_user,
    )
