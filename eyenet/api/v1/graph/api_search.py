"""GET /v1/graph/search — actor lookup by handle/alias."""

from __future__ import annotations

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.actors import CursorPageActorSummary

router = APIRouter(tags=["graph"])


@router.get(
    "/graph/search",
    operation_id="graph_search",
    response_model=CursorPageActorSummary,
    status_code=200,
)
async def graph_search(
    q: str = Query(min_length=1, max_length=256),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = Query(default=False),
) -> CursorPageActorSummary:
    raise NotImplementedError("graph_search (M9.0 skeleton)")
