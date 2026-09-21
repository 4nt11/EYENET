# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/system — authenticated host self-report (CPU / RAM / disk / load).

Gated behind ``read:metrics`` — there is no anonymous system endpoint. Host
stats never go on an unauthenticated surface (a portscan-visible fingerprint);
the unauthenticated /readyz carries only up/down flags. API_PLAN §3.6.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

import eyenet
from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.system import SystemStats
from eyenet.telemetry import sysstats

router = APIRouter(tags=["health"])


@router.get("/system", operation_id="system_stats", response_model=SystemStats)
async def system_stats(
    request: Request,
    _: Annotated[CurrentUser, Depends(RequireScope("read:metrics"))],
) -> SystemStats:
    return SystemStats(
        **sysstats.snapshot(request.app.state.data_dir),
        version=eyenet.__version__,
    )
