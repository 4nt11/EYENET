"""GET /v1/actors/{actor_id} — full actor detail."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.actors import ActorDetail

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}",
    operation_id="actors_get",
    response_model=ActorDetail,
    status_code=200,
)
async def actors_get(actor_id: UUID) -> ActorDetail:
    raise NotImplementedError("actors_get (M9.0 skeleton)")
