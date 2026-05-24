"""GET /v1/metrics — Prometheus text-format scrape endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["health"])


@router.get(
    "/metrics",
    operation_id="health_metrics",
    response_class=PlainTextResponse,
    status_code=200,
)
async def health_metrics() -> PlainTextResponse:
    raise NotImplementedError("health_metrics (M9.0 skeleton)")
