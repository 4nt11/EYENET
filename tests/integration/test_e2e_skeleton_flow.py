"""All five skeletons over MemoryBus — wake up, subscribe, shutdown clean."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.engine.skeleton import EngineSkeleton
from eyenet.graph.graph import Graph
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.linker.linker import Linker
from eyenet.sensor.skeleton import SensorSkeleton
from eyenet.service import run_service
from eyenet.storage import SQLiteStorage

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures/corpora/synthetic_small.jsonl"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_fleet_lifecycle(tmp_path: Path) -> None:
    session = tmp_path / "tg_alpha.session"
    session.touch()
    cfg_path = tmp_path / "identities.toml"
    dump(
        IdentityFile(
            identities=[
                IdentityFileEntry(
                    name="tg_alpha",
                    source="telegram",  # type: ignore[arg-type]
                    session_path=str(session),
                    cooldown_seconds=0,
                )
            ]
        ),
        cfg_path,
    )
    pool = FileIdentityPool(cfg_path)

    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    fixture = _FIXTURE_PATH

    services = [
        SensorSkeleton(bus=bus, storage=storage),
        EngineSkeleton(bus=bus, storage=storage),
        Linker(bus=bus, storage=storage),
        Graph(bus=bus, storage=storage),
        TelegramCollectorStub(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name="tg_alpha",
            fixture_path=fixture,
        ),
    ]

    tasks = [
        asyncio.create_task(run_service(s, tick_interval=0.01 if "collector" in s.name else 0.0))
        for s in services
    ]
    await asyncio.sleep(0.2)

    for s in services:
        await s.shutdown()
    await asyncio.gather(*tasks)

    rows = await storage.all_audit()
    services_seen = {r.service for r in rows}
    assert services_seen >= {"sensor", "engine", "linker", "graph", "collector.telegram"}

    starts = [r for r in rows if r.event == "service.start"]
    stops = [r for r in rows if r.event == "service.stop"]
    assert len(starts) == 5
    assert len(stops) == 5

    await storage.close()
