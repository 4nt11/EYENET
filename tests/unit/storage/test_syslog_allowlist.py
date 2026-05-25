"""SystemLog allowlist gating."""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.contracts.enums import SystemLogLevel
from eyenet.storage.factory import get_repository


@pytest.mark.unit
@pytest.mark.asyncio
async def test_allowlisted_lifecycle_persists(tmp_path: Path) -> None:
    s = get_repository(data_dir=tmp_path)
    try:
        ok = await s.append_syslog(
            level=SystemLogLevel.LIFECYCLE,
            service="engine",
            instance_id="eng_1",
            event="service.start",
            message="engine booted",
        )
        assert ok is True
    finally:
        await s.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_off_allowlist_lifecycle_dropped(tmp_path: Path) -> None:
    s = get_repository(data_dir=tmp_path)
    try:
        ok = await s.append_syslog(
            level=SystemLogLevel.LIFECYCLE,
            service="engine",
            instance_id="eng_1",
            event="totally.made.up",
            message="should not persist",
        )
        assert ok is False
    finally:
        await s.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_warn_always_persists(tmp_path: Path) -> None:
    s = get_repository(data_dir=tmp_path)
    try:
        ok = await s.append_syslog(
            level=SystemLogLevel.WARN,
            service="engine",
            instance_id="eng_1",
            event="random.warn.event",  # off-allowlist, but level=warn → persists
            message="something fishy",
        )
        assert ok is True
    finally:
        await s.close()
