"""POST /v1/identities/{identity_id}/burn — permanently retire a compromised identity.

Sets state=BURNED + role=QUARANTINE (via ``burn_identity``): the identity never
re-enters rotation. This is the under-attack action — an operator who believes an
identity is blown torches it outright.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1.identities._act import act_on_identity
from eyenet.api.v1.schemas.identities import IdentityActionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts.enums import IdentityState
from eyenet.contracts.identity import SUBJECT_IDENTITY_BURNED
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])


@router.post(
    "/identities/{identity_id}/burn",
    operation_id="identities_burn",
    response_model=WriteAccepted,
    status_code=202,
)
async def identities_burn(
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
        action="burned",
        subject=SUBJECT_IDENTITY_BURNED,
        new_state=IdentityState.BURNED,
        burn=True,
        storage=storage,
        audit=audit,
        publisher=publisher,
        current_user=current_user,
    )
