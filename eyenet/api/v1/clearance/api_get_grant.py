"""GET /v1/clearance/grants/{grant_id} — full grant detail (§4.8)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.clearance import ClearanceGrantDetail

router = APIRouter(tags=["clearance"])


@router.get(
    "/clearance/grants/{grant_id}",
    operation_id="clearance_get_grant",
    response_model=ClearanceGrantDetail,
    status_code=200,
)
async def clearance_get_grant(grant_id: UUID) -> ClearanceGrantDetail:
    raise NotImplementedError("clearance_get_grant (M9.0 skeleton)")
