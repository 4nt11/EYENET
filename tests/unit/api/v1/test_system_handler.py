# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for GET /v1/system (auth is exercised in integration)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

import eyenet
from eyenet.api.deps import CurrentUser
from eyenet.api.v1.schemas.system import SystemStats
from eyenet.api.v1.system.api_get_system import system_stats
from eyenet.bus import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.storage.factory import get_repository

pytestmark = pytest.mark.unit


async def test_system_stats_reports_host(
    mkuser: Callable[..., CurrentUser], tmp_path: Path
) -> None:
    state = SimpleNamespace(
        data_dir=tmp_path,
        storage=get_repository(in_memory=True),
        publisher=BusEnvelopePublisher(MemoryBus()),
        verifying_keys={"kid-a": object()},
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    result = await system_stats(request, mkuser("read:metrics"))  # type: ignore[arg-type]
    assert isinstance(result, SystemStats)
    assert result.cpu_percent >= 0.0
    assert result.mem.total > 0
    assert result.disk.data.total > 0
    assert result.uptime_seconds >= 0.0
    assert result.version == eyenet.__version__
    # Component detail is real, not fabricated.
    assert result.components.bus.startswith("memory")
    assert result.components.auth_keys == "1 verifying key"
