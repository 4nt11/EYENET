"""GET /v1/healthz — liveness probe (always 200 once process is up)."""

from __future__ import annotations

from fastapi import APIRouter

from eyenet.api.v1.schemas.health import HealthStatus

router = APIRouter(tags=["health"])


@router.get(
    "/healthz",
    operation_id="health_live",
    response_model=HealthStatus,
    status_code=200,
)
async def health_live() -> HealthStatus:
    raise NotImplementedError("health_live (M9.0 skeleton)")
