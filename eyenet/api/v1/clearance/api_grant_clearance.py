"""POST /v1/clearance/grants — grant a clearance scope (§4.8). Requires admin:clearance."""

from __future__ import annotations

from fastapi import APIRouter, Header

from eyenet.api.v1.schemas.clearance import ClearanceGrantDetail, ClearanceGrantRequest

router = APIRouter(tags=["clearance"])


@router.post(
    "/clearance/grants",
    operation_id="clearance_grant",
    response_model=ClearanceGrantDetail,
    status_code=201,
)
async def clearance_grant(
    body: ClearanceGrantRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
) -> ClearanceGrantDetail:
    raise NotImplementedError("clearance_grant (M9.0 skeleton)")
