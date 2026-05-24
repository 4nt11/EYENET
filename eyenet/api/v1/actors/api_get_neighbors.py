"""GET /v1/actors/{actor_id}/neighbors — graph neighbors (linked actors + persona)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.actors import NeighborList

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}/neighbors",
    operation_id="actors_neighbors",
    response_model=NeighborList,
    status_code=200,
)
async def actors_neighbors(actor_id: UUID) -> NeighborList:
    raise NotImplementedError("actors_neighbors (M9.0 skeleton)")
