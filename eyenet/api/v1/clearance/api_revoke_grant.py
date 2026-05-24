"""POST /v1/clearance/grants/{grant_id}/revoke — revoke a clearance grant (§4.8)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header

from eyenet.api.v1.schemas.clearance import ClearanceRevokeRequest
from eyenet.api.v1.schemas.writes import WriteAccepted

router = APIRouter(tags=["clearance"])


@router.post(
    "/clearance/grants/{grant_id}/revoke",
    operation_id="clearance_revoke_grant",
    response_model=WriteAccepted,
    status_code=202,
)
async def clearance_revoke_grant(
    grant_id: UUID,
    body: ClearanceRevokeRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> WriteAccepted:
    raise NotImplementedError("clearance_revoke_grant (M9.0 skeleton)")
