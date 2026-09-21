"""POST /v1/identities/{identity_id}/release — operator releases an identity (AVAILABLE)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1.identities._act import act_on_identity
from eyenet.api.v1.schemas.identities import IdentityActionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import IdentityState
from eyenet.contracts.identity import SUBJECT_IDENTITY_RELEASED
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])


@router.post(
    "/identities/{identity_id}/release",
    operation_id="identities_release",
    response_model=WriteAccepted,
    status_code=202,
)
async def identities_release(
    body: IdentityActionRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    identity_id: str = Path(..., min_length=1, max_length=128),
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for the OpenAPI surface
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> WriteAccepted:
    return await act_on_identity(
        identity_id_raw=identity_id,
        body=body,
        action="released",
        subject=SUBJECT_IDENTITY_RELEASED,
        new_state=IdentityState.AVAILABLE,
        burn=False,
        storage=storage,
        audit=audit,
        publisher=publisher,
        current_user=current_user,
    )
