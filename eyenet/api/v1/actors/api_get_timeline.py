"""GET /v1/actors/{actor_id}/timeline — interleaved messages + observations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.actors import CursorPageTimelineEntry

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}/timeline",
    operation_id="actors_timeline",
    response_model=CursorPageTimelineEntry,
    status_code=200,
)
async def actors_timeline(
    actor_id: UUID,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = Query(default=False),
) -> CursorPageTimelineEntry:
    raise NotImplementedError("actors_timeline (M9.0 skeleton)")
