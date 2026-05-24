"""GET /v1/linkages — paginated list, filterable by state/actor."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.enums import LinkageState
from eyenet.api.v1.schemas.linkages import CursorPageLinkageSummary

router = APIRouter(tags=["linkages"])


@router.get(
    "/linkages",
    operation_id="linkages_list",
    response_model=CursorPageLinkageSummary,
    status_code=200,
)
async def linkages_list(
    state: LinkageState | None = Query(default=None),
    actor_id: UUID | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = Query(default=False),
) -> CursorPageLinkageSummary:
    raise NotImplementedError("linkages_list (M9.0 skeleton)")
