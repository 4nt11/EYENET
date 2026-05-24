"""GET /v1/readyz — readiness probe (per-component health)."""

from __future__ import annotations

from fastapi import APIRouter

from eyenet.api.v1.schemas.health import ReadyStatus

router = APIRouter(tags=["health"])


@router.get(
    "/readyz",
    operation_id="health_ready",
    response_model=ReadyStatus,
    status_code=200,
)
async def health_ready() -> ReadyStatus:
    raise NotImplementedError("health_ready (M9.0 skeleton)")
