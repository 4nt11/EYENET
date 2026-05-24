"""GET /v1/actors/{actor_id}/observations — paginated observations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.actors import CursorPageObservationSummary

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}/observations",
    operation_id="actors_observations",
    response_model=CursorPageObservationSummary,
    status_code=200,
)
async def actors_observations(
    actor_id: UUID,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = Query(default=False),
) -> CursorPageObservationSummary:
    raise NotImplementedError("actors_observations (M9.0 skeleton)")
