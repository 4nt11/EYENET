# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/system — authenticated host self-report (CPU / RAM / disk / load).

Gated behind ``read:metrics`` — there is no anonymous system endpoint. Host
stats never go on an unauthenticated surface (a portscan-visible fingerprint);
the unauthenticated /readyz carries only up/down flags. API_PLAN §3.6.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

import eyenet
from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.system import ComponentDetail, SystemStats
from eyenet.telemetry import sysstats

router = APIRouter(tags=["health"])

_KIB = 1024
_MIB = _KIB * 1024


def _fmt_bytes(n: int) -> str:
    if n >= _MIB:
        return f"{n / _MIB:.1f} MB"
    if n >= _KIB:
        return f"{n / _KIB:.0f} KB"
    return f"{n} B"


def _components(state: Any) -> ComponentDetail:
    """Real per-subsystem detail from the live app state (never fabricated)."""
    backend = type(state.storage).__name__.removesuffix("Repository").lower()
    parts = [backend]
    data_dir = state.data_dir
    if data_dir is not None:
        for label, fname in (("main", "main.db"), ("audit", "audit.db")):
            db = data_dir / fname
            if db.exists():
                parts.append(f"{label} {_fmt_bytes(db.stat().st_size)}")

    bus = state.publisher.bus
    kind = type(bus).__name__.removesuffix("Bus").lower()
    bus_detail = f"{kind} · {'connected' if bus.connected() else 'down'}"

    n = len(state.verifying_keys)
    keys_detail = f"{n} verifying key{'' if n == 1 else 's'}"

    return ComponentDetail(storage=" · ".join(parts), bus=bus_detail, auth_keys=keys_detail)


@router.get("/system", operation_id="system_stats", response_model=SystemStats)
async def system_stats(
    request: Request,
    _: Annotated[CurrentUser, Depends(RequireScope("read:metrics"))],
) -> SystemStats:
    return SystemStats(
        **sysstats.snapshot(request.app.state.data_dir),
        version=eyenet.__version__,
        components=_components(request.app.state),
    )
