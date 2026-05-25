"""ServiceBase + run_service: starts, subscribes, audit emit, clean shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eyenet.bus import MemoryBus
from eyenet.contracts.audit import verify_chain
from eyenet.service import ServiceBase, run_service
from eyenet.storage import SQLiteStorage


class _Toy(ServiceBase):
    @property
    def name(self) -> str:
        return "toy"

    @property
    def instance_id(self) -> str:
        return "toy_1"

    async def on_subscribe(self) -> None:
        return None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_to_stop_clean(tmp_path: Path) -> None:
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path)
    svc = _Toy(bus=bus, storage=storage)

    task = asyncio.create_task(run_service(svc))
    # Give it a tick to enter the wait loop.
    await asyncio.sleep(0)
    await svc.shutdown()
    await asyncio.wait_for(task, timeout=2.0)

    rows = await storage.all_audit()
    events = [r.event for r in rows]
    assert "service.start" in events
    assert "service.stop" in events

    ok, broken = verify_chain(rows)
    assert ok, f"chain broken at {broken}"

    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publishes_service_start_on_bus(tmp_path: Path) -> None:
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path)
    seen: list[str] = []

    async def cap(subject: str, _payload: bytes, _headers: dict[str, str]) -> None:
        seen.append(subject)

    await bus.subscribe("eyenet.audit.>", cap)

    svc = _Toy(bus=bus, storage=storage)
    task = asyncio.create_task(run_service(svc))
    await asyncio.sleep(0.05)
    await svc.shutdown()
    await asyncio.wait_for(task, timeout=2.0)

    assert "eyenet.audit.toy" in seen

    await storage.close()
