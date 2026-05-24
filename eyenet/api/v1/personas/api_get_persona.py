"""GET /v1/personas/{persona_id} — persona detail."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.personas import PersonaDetail

router = APIRouter(tags=["personas"])


@router.get(
    "/personas/{persona_id}",
    operation_id="personas_get",
    response_model=PersonaDetail,
    status_code=200,
)
async def personas_get(persona_id: UUID) -> PersonaDetail:
    raise NotImplementedError("personas_get (M9.0 skeleton)")
