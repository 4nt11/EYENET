# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for /v1/healthz + /v1/readyz (ASGI routing is covered
by tests/integration/api/test_probes.py; coverage is credited here)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Response
from sqlalchemy.exc import OperationalError

from eyenet.api.v1.health.api_healthz import health_live
from eyenet.api.v1.health.api_readyz import health_ready
from eyenet.telemetry import metrics

pytestmark = pytest.mark.unit


def _request(*, storage_ok: bool = True, bus_ok: bool = True, keys: tuple = ("k",)):
    async def _ok_ping() -> None:
        return None

    async def _bad_ping() -> None:
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                storage=SimpleNamespace(ping=_ok_ping if storage_ok else _bad_ping),
                publisher=SimpleNamespace(bus=SimpleNamespace(connected=lambda: bus_ok)),
                verifying_keys={k: k for k in keys},
            )
        )
    )


async def test_health_live_is_ok() -> None:
    result = await health_live()
    assert result.status == "ok"
    assert metrics._health["healthy"] == 1.0


async def test_readyz_all_up_is_ready_200() -> None:
    response = Response()
    result = await health_ready(_request(), response)  # type: ignore[arg-type]
    assert result.status == "ready"
    assert (result.components.storage, result.components.bus, result.components.auth_keys) == (
        "up",
        "up",
        "up",
    )
    assert response.status_code == 200
    assert metrics._health["ready:storage"] == 1.0


async def test_readyz_storage_down_is_degraded_503() -> None:
    response = Response()
    result = await health_ready(_request(storage_ok=False), response)  # type: ignore[arg-type]
    assert result.status == "degraded"
    assert result.components.storage == "down"
    assert response.status_code == 503
    assert metrics._health["ready:storage"] == 0.0


async def test_readyz_bus_down_is_degraded() -> None:
    response = Response()
    result = await health_ready(_request(bus_ok=False), response)  # type: ignore[arg-type]
    assert result.status == "degraded"
    assert result.components.bus == "down"
    assert response.status_code == 503


async def test_readyz_no_keys_is_degraded() -> None:
    response = Response()
    result = await health_ready(_request(keys=()), response)  # type: ignore[arg-type]
    assert result.status == "degraded"
    assert result.components.auth_keys == "down"  # pragma: allowlist secret
    assert response.status_code == 503
