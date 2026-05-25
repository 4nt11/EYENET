"""PLAN §7.3 — multi-collector validation.

Two collectors with distinct identities + one sensor on a `MemoryBus`:
- distinct `instance_id`s
- separate audit rows (one per service)
- sensor receives both streams via queue group
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.sensor.skeleton import SensorSkeleton
from eyenet.service import run_service
from eyenet.storage.factory import get_repository

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures/corpora/synthetic_small.jsonl"


def _setup_pool(tmp_path: Path, names: list[str]) -> Path:
    entries = []
    for name in names:
        session = tmp_path / f"{name}.session"
        session.touch()
        entries.append(
            IdentityFileEntry(
                name=name,
                source="telegram",  # type: ignore[arg-type]
                session_path=str(session),
                cooldown_seconds=0,
            )
        )
    cfg_path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=entries), cfg_path)
    return cfg_path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_collectors_one_sensor(tmp_path: Path) -> None:
    cfg_path = _setup_pool(tmp_path, ["tg_alpha", "tg_beta"])
    pool = FileIdentityPool(cfg_path)

    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data")

    fixture = _FIXTURE_PATH

    sensor = SensorSkeleton(bus=bus, storage=storage)
    coll_a = TelegramCollectorStub(
        bus=bus, storage=storage, pool=pool, identity_name="tg_alpha", fixture_path=fixture
    )
    coll_b = TelegramCollectorStub(
        bus=bus, storage=storage, pool=pool, identity_name="tg_beta", fixture_path=fixture
    )

    # Distinct instance_ids — load-bearing per PLAN §2.1.
    assert coll_a.instance_id != coll_b.instance_id

    # Sensor receives raw envelopes — capture count via instrumentation.
    received: list[str] = []

    original_subscribe = sensor.on_subscribe

    async def patched_subscribe() -> None:
        await original_subscribe()

        async def _recorder(subject: str, _p: bytes, _h: dict[str, str]) -> None:
            received.append(subject)

        await bus.subscribe("raw.message.>", _recorder)

    sensor.on_subscribe = patched_subscribe  # type: ignore[method-assign]

    sensor_task = asyncio.create_task(run_service(sensor))
    coll_a_task = asyncio.create_task(run_service(coll_a, tick_interval=0.01))
    coll_b_task = asyncio.create_task(run_service(coll_b, tick_interval=0.01))

    # Let the fixtures drain.
    await asyncio.sleep(0.3)

    await sensor.shutdown()
    await coll_a.shutdown()
    await coll_b.shutdown()
    await asyncio.gather(sensor_task, coll_a_task, coll_b_task)

    # Each fixture has 3 lines; 2 collectors → 6 raw messages on the bus.
    assert len(received) == 6
    # Both instance_ids appear in the subject set.
    subjects = set(received)
    assert any(coll_a.instance_id in s for s in subjects)
    assert any(coll_b.instance_id in s for s in subjects)

    rows = await storage.all_audit()
    services = {r.service for r in rows}
    assert {"sensor", "collector.telegram"} <= services

    await storage.close()
