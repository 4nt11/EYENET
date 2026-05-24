"""GET /v1/personas/{persona_id}/members — paginated members."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.personas import CursorPagePersonaMember

router = APIRouter(tags=["personas"])


@router.get(
    "/personas/{persona_id}/members",
    operation_id="personas_members",
    response_model=CursorPagePersonaMember,
    status_code=200,
)
async def personas_members(
    persona_id: UUID,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = Query(default=False),
) -> CursorPagePersonaMember:
    raise NotImplementedError("personas_members (M9.0 skeleton)")
