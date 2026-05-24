"""GET /v1/graph/stats — global graph counters."""

from __future__ import annotations

from fastapi import APIRouter

from eyenet.api.v1.schemas.graph import GraphStats

router = APIRouter(tags=["graph"])


@router.get(
    "/graph/stats",
    operation_id="graph_stats",
    response_model=GraphStats,
    status_code=200,
)
async def graph_stats() -> GraphStats:
    raise NotImplementedError("graph_stats (M9.0 skeleton)")
