"""GET /v1/readyz — readiness probe (per-component health).

Unauthenticated (k8s probes it) and carries NO host stats — only up/down flags.
200 when every component is up; 503 (same ``ReadyStatus`` body) when any is down,
so an operator/curl sees exactly which one. Also refreshes the M9.6 health gauges
via ``set_health`` so they reflect live probes, not boot-time optimism.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from eyenet.api.v1.schemas.health import ReadyComponents, ReadyStatus
from eyenet.telemetry.metrics import set_health

router = APIRouter(tags=["health"])


async def _storage_up(request: Request) -> bool:
    try:
        await request.app.state.storage.ping()
    except SQLAlchemyError:
        return False
    return True


def _flag(up: bool) -> Literal["up", "down"]:
    return "up" if up else "down"


@router.get(
    "/readyz",
    operation_id="health_ready",
    response_model=ReadyStatus,
    status_code=200,
)
async def health_ready(request: Request, response: Response) -> ReadyStatus:
    storage_up = await _storage_up(request)
    bus_up = bool(request.app.state.publisher.bus.connected())
    keys_up = bool(request.app.state.verifying_keys)

    # Refresh the observable gauges (component keys mirror app.py boot wiring).
    set_health("storage_open", value=storage_up)
    set_health("bus_connected", value=bus_up)
    set_health("ready:storage", value=storage_up)
    set_health("ready:bus", value=bus_up)
    set_health("ready:jwt_keys", value=keys_up)

    ready = storage_up and bus_up and keys_up
    if not ready:
        response.status_code = 503
    return ReadyStatus(
        status="ready" if ready else "degraded",
        components=ReadyComponents(
            storage=_flag(storage_up),
            bus=_flag(bus_up),
            auth_keys=_flag(keys_up),
        ),
    )
