"""GET /v1/clearance/grants — list clearance grants (§4.8)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.clearance import CursorPageClearanceGrantSummary
from eyenet.api.v1.schemas.enums import ClearanceScope

router = APIRouter(tags=["clearance"])


@router.get(
    "/clearance/grants",
    operation_id="clearance_list_grants",
    response_model=CursorPageClearanceGrantSummary,
    status_code=200,
)
async def clearance_list_grants(
    cursor: str | None = Query(default=None, max_length=4096),
    limit: int = Query(default=50, ge=1, le=500),
    include_total: int = Query(default=0, ge=0, le=1),
    active_only: int = Query(default=0, ge=0, le=1),
    user_id: UUID | None = Query(default=None),
    scope: ClearanceScope | None = Query(default=None),
) -> CursorPageClearanceGrantSummary:
    raise NotImplementedError("clearance_list_grants (M9.0 skeleton)")
