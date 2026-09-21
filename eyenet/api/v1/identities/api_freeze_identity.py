"""POST /v1/identities/{identity_id}/freeze — soft-freeze one identity (FROZEN)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1.identities._act import act_on_identity
from eyenet.api.v1.schemas.identities import IdentityActionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import IdentityState
from eyenet.contracts.identity import SUBJECT_IDENTITY_FROZEN
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])


@router.post(
    "/identities/{identity_id}/freeze",
    operation_id="identities_freeze",
    response_model=WriteAccepted,
    status_code=202,
)
async def identities_freeze(
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
        action="frozen",
        subject=SUBJECT_IDENTITY_FROZEN,
        new_state=IdentityState.FROZEN,
        burn=False,
        storage=storage,
        audit=audit,
        publisher=publisher,
        current_user=current_user,
    )
