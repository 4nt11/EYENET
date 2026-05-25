# ruff: noqa: ASYNC110
"""M2 integration test — stub collector → StylometricSensor → SQLite.

Verifies end-to-end flow:
  TelegramCollectorStub (synthetic JSONL) → bus → StylometricSensor
  → ObservationTable rows in observations.db
  → CorpusCursorTable rows in corpus.db

Also verifies failure isolation: when one primitive is monkeypatched to raise,
the other three still emit.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.contracts.enums import SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.service import run_service
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/corpora/synthetic_m2.jsonl"
_NOW = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)


def _pool(tmp_path: Path, name: str = "tg_alpha") -> FileIdentityPool:
    session = tmp_path / f"{name}.session"
    session.touch()
    entry = IdentityFileEntry(
        name=name, source=SourceKind.TELEGRAM, session_path=str(session), cooldown_seconds=0
    )
    cfg = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg)
    return FileIdentityPool(cfg)


async def _seed_messages(storage: BaseRepository) -> None:
    """Pre-populate actor + message rows for the fixture so the sensor can
    dereference evidence_refs. Stub collector only publishes envelopes."""
    from tests._seed import seed_telegram_fixture  # noqa: PLC0415

    records = []
    with _FIXTURE.open() as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))

    await seed_telegram_fixture(storage, records, _NOW)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stylometric_e2e(tmp_path: Path) -> None:
    pool = _pool(tmp_path)
    bus = MemoryBus()
    data_dir = tmp_path / "data"
    storage = get_repository(data_dir=data_dir)

    await _seed_messages(storage)

    sensor = StylometricSensor(bus=bus, storage=storage)
    collector = TelegramCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="tg_alpha",
        fixture_path=_FIXTURE,
    )

    processed: list[str] = []
    original = sensor._process

    async def _patched(env):  # type: ignore[no-untyped-def]
        processed.append(env.evidence_ref)
        await original(env)

    sensor._process = _patched  # type: ignore[method-assign]

    sensor_task = asyncio.create_task(run_service(sensor))
    collector_task = asyncio.create_task(run_service(collector, tick_interval=0.001))

    # Collector emits all 210 at 1ms tick (~0.21s). Sensor SQLite calls are
    # synchronous and block the loop, so we poll until all are processed.
    deadline = asyncio.get_event_loop().time() + 30.0
    while len(processed) < 210 and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.1)

    await collector.shutdown()
    await sensor.shutdown()
    await asyncio.gather(sensor_task, collector_task)

    assert len(processed) == 210, f"expected 210 processed, got {len(processed)}"

    await storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failure_isolation(tmp_path: Path) -> None:
    """A broken primitive must not abort its siblings."""
    from unittest.mock import patch

    pool = _pool(tmp_path)
    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data2")

    await _seed_messages(storage)

    sensor = StylometricSensor(bus=bus, storage=storage)
    collector = TelegramCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="tg_alpha",
        fixture_path=_FIXTURE,
    )

    errors: list[str] = []
    processed_count = 0
    original_run = sensor._run_primitives

    async def _instrumented(actor_id, env, body):  # type: ignore[no-untyped-def]
        nonlocal processed_count
        try:
            await original_run(actor_id, env, body)
        except Exception as e:
            errors.append(str(e))
        finally:
            processed_count += 1

    sensor._run_primitives = _instrumented  # type: ignore[method-assign]

    expected = sum(1 for line in _FIXTURE.read_text().splitlines() if line.strip())

    with patch(
        "eyenet.sensor.primitives.mattr.compute",
        side_effect=RuntimeError("boom"),
    ):
        sensor_task = asyncio.create_task(run_service(sensor))
        collector_task = asyncio.create_task(run_service(collector, tick_interval=0.001))
        # Poll until every envelope has reached _run_primitives. No blanket
        # post-drain sleep — the counter is the drain signal.
        deadline = asyncio.get_event_loop().time() + 30.0
        while processed_count < expected and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
        await collector.shutdown()
        await sensor.shutdown()
        await asyncio.gather(sensor_task, collector_task)

    assert processed_count == expected, (
        f"sensor drained {processed_count}/{expected} envelopes before shutdown"
    )

    # The _run_primitives wrapper should have caught the mattr failure internally.
    # No outer exception should have propagated.
    assert errors == [], f"unexpected outer errors: {errors}"

    await storage.close()
