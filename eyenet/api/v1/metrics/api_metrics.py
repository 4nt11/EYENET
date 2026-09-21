# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/metrics — Prometheus text-format scrape endpoint (M9.6, §11.7.1).

Dual-gated: the caller must hold ``read:metrics`` (there is no anonymous metrics
endpoint) AND ``EYENET_API_METRICS_ENABLED`` must be truthy — a deployment with
scrape off returns 404 even to an authorized caller, so the status code leaks no
signal about whether monitoring is wired. Operators run Prometheus under a
service-account PAT holding only ``read:metrics`` (§11.7.1).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound
from eyenet.telemetry.metrics import metrics_enabled, prometheus_exposition

router = APIRouter(tags=["health"])


@router.get("/metrics", operation_id="health_metrics")
async def health_metrics(
    _: Annotated[CurrentUser, Depends(RequireScope("read:metrics"))],
) -> Response:
    if not metrics_enabled():
        raise ResourceNotFound("metrics")
    body, content_type = prometheus_exposition()
    return Response(content=body, media_type=content_type)
