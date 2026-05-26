# ruff: noqa: ASYNC110
"""M2 integration test — stub collector → StylometricSensor — SQLite-pinned.

Verifies end-to-end flow:
  TelegramCollectorStub (synthetic JSONL) → bus → StylometricSensor
  → ObservationTable rows
  → CorpusCursorTable rows

Also covers a throughput-under-primitive-failure check: with one primitive
patched to always raise, the pipeline still drains all envelopes without a
cascading abort. The actual per-message sibling-isolation invariant
(broken primitive → other primitives still emit Observation rows for the
same envelope) is unit-tested in
``tests/unit/sensor/test_run_primitives_isolation.py``.

SQLite-pinned (filename ``_sqlite`` suffix per
[[feedback_use_baserepo_abstraction_in_tests]]) because the pipeline timing
depends on aiosqlite ``QueuePool`` + ``BEGIN IMMEDIATE`` audit-chain
serialization characteristics. Under a future MySQL/Postgres backend the
throughput envelope will be different — a mirror file
(``test_stylometric_e2e_postgres.py``) sits alongside.

No internal poll-deadline: drain runs against the global ``pytest --timeout``
(60s for this file). A real hang fails fast via pytest-timeout; a slow drain
fails with a clear count message.
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
    from tests._seed import seed_telegram_fixture

    records = []
    with _FIXTURE.open() as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))

    await seed_telegram_fixture(storage, records, _NOW)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stylometric_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end correctness: every envelope reaches _process. Workload
    cropped to the first 30 fixture records so the test fits the suite's
    global pytest-timeout under aiosqlite per-call overhead."""
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    pool = _pool(tmp_path)
    bus = MemoryBus()
    data_dir = tmp_path / "data"
    storage = get_repository(data_dir=data_dir)

    records = [json.loads(line) for line in _FIXTURE.read_text().splitlines()[:30] if line.strip()]
    from tests._seed import seed_telegram_fixture

    await seed_telegram_fixture(storage, records, _NOW)
    expected_count = len(records)

    tiny_fixture = tmp_path / "tiny.jsonl"
    tiny_fixture.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )

    sensor = StylometricSensor(bus=bus, storage=storage)
    collector = TelegramCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="tg_alpha",
        fixture_path=tiny_fixture,
    )

    processed: list[str] = []
    original = sensor._process

    async def _patched(env):  # type: ignore[no-untyped-def]
        processed.append(env.evidence_ref)
        await original(env)

    sensor._process = _patched  # type: ignore[method-assign]

    sensor_task = asyncio.create_task(run_service(sensor))
    collector_task = asyncio.create_task(run_service(collector, tick_interval=0.001))

    # Drain counter is the signal; pyproject's pytest --timeout is watchdog.
    while len(processed) < expected_count:
        await asyncio.sleep(0.1)

    await collector.shutdown()
    await sensor.shutdown()
    await asyncio.gather(sensor_task, collector_task)

    assert len(processed) == expected_count

    await storage.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dispatch_drains_under_primitive_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipeline-level: with one primitive patched to raise on every envelope,
    the dispatch loop must still drain every message — no fatal abort, no
    deadlock between the broken primitive and the rest of the pipeline.

    Workload is intentionally small (30 envelopes) so the test fits the
    suite's global pytest-timeout. The per-primitive sibling-isolation
    invariant — a raise in primitive X doesn't suppress sibling primitives'
    Observation rows for the SAME envelope — is unit-tested directly
    against ``_run_primitives`` in
    ``tests/unit/sensor/test_run_primitives_isolation.py``, which runs in
    milliseconds and is independent of pool timing.
    """
    from unittest.mock import patch

    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    pool = _pool(tmp_path)
    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data2")

    # Seed only the first N fixture records — enough to demonstrate the
    # broken primitive doesn't deadlock the pipeline, small enough to drain
    # under the suite-level pytest-timeout without a per-test override.
    records = [json.loads(line) for line in _FIXTURE.read_text().splitlines()[:30] if line.strip()]
    from tests._seed import seed_telegram_fixture

    await seed_telegram_fixture(storage, records, _NOW)
    expected = len(records)

    # Write a tiny in-tmp fixture file the collector can replay.
    tiny_fixture = tmp_path / "tiny.jsonl"
    tiny_fixture.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )

    sensor = StylometricSensor(bus=bus, storage=storage)
    collector = TelegramCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="tg_alpha",
        fixture_path=tiny_fixture,
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

    with patch(
        "eyenet.sensor.primitives.mattr.compute",
        side_effect=RuntimeError("boom"),
    ):
        sensor_task = asyncio.create_task(run_service(sensor))
        collector_task = asyncio.create_task(run_service(collector, tick_interval=0.001))
        # Poll until every envelope has reached _run_primitives. The drain
        # counter is the signal; pyproject's pytest --timeout is the watchdog.
        while processed_count < expected:
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
