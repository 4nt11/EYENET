"""M3 engine end-to-end integration test.

Verifies the full Collector → Sensor → Engine pipeline on MemoryBus:
  TelegramCollectorStub (synthetic_m3.jsonl)
  → raw.message.telegram.* bus subject
  → StylometricSensor (computes primitives including conversation_initiation_rate)
  → ObservationStore rows
  → Engine (maps observations → ProfileRow snapshots, runs recipes)
  → ProfileStore rows with role_signal

Synthetic fixture has two actors:
  - actor_lurker: 50 messages, initiation_rate=0.04 → recipe "lurker_or_observer"
  - actor_bot:    50 messages, initiation_rate=1.0 + low MATTR → recipe "bot_or_automated_poster"
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.contracts.enums import SourceKind
from eyenet.engine.engine import Engine
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.service import run_service
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from tests._seed import seed_telegram_fixture

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/corpora/synthetic_m3.jsonl"
_NOW = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)

_LURKER_KEY = "actor:" + "a" * 64
_BOT_KEY = "actor:" + "b" * 64


def _pool(tmp_path: Path) -> FileIdentityPool:
    session = tmp_path / "tg_alpha.session"
    session.touch()
    entry = IdentityFileEntry(
        name="tg_alpha", source=SourceKind.TELEGRAM, session_path=str(session), cooldown_seconds=0
    )
    cfg = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg)
    return FileIdentityPool(cfg)


async def _seed_messages(storage: BaseRepository) -> dict[str, UUID]:
    """Seed MessageTable rows with reply_to_msg_id set for replies.

    Returns actor_key → actor_id mapping. Delegates the seed mechanics
    to ``tests._seed.seed_telegram_fixture``.
    """
    records: list[dict[str, Any]] = []
    with _FIXTURE.open() as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))

    _, _, actor_ids = await seed_telegram_fixture(
        storage, records, _NOW, group_title="Test M3"
    )
    return actor_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_engine_e2e_role_signals(tmp_path: Path) -> None:
    """Full pipeline: fixture → bus → sensor → engine → ProfileStore.

    Asserts that both synthetic actors receive the expected role_signal.
    """
    pool = _pool(tmp_path)
    bus = MemoryBus()
    data_dir = tmp_path / "data"
    storage = get_repository(data_dir=data_dir)

    actor_ids = await _seed_messages(storage)

    lurker_actor_id = actor_ids[_LURKER_KEY]
    bot_actor_id = actor_ids[_BOT_KEY]

    sensor = StylometricSensor(bus=bus, storage=storage)
    engine = Engine(bus=bus, storage=storage)
    collector = TelegramCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="tg_alpha",
        fixture_path=_FIXTURE,
    )

    sensor_task = asyncio.create_task(run_service(sensor))
    engine_task = asyncio.create_task(run_service(engine))
    collector_task = asyncio.create_task(run_service(collector, tick_interval=0.001))

    # Wait until both actors have a profile with a non-None role_signal, or timeout.
    async def _get_role(actor_id: UUID) -> str | None:
        row = await storage.get_current_profile(actor_id)
        return (
            str(row.role_signal)  # type: ignore[attr-defined]
            if row and row.role_signal  # type: ignore[attr-defined]
            else None
        )

    deadline = asyncio.get_event_loop().time() + 60.0
    while asyncio.get_event_loop().time() < deadline:
        lurker_role = await _get_role(lurker_actor_id)
        bot_role = await _get_role(bot_actor_id)
        if lurker_role is not None and bot_role is not None:
            break
        await asyncio.sleep(0.2)

    await collector.shutdown()
    await sensor.shutdown()
    await engine.shutdown()
    await asyncio.gather(sensor_task, engine_task, collector_task)
    await storage.close()

    lurker_role = await _get_role(lurker_actor_id)
    bot_role = await _get_role(bot_actor_id)

    assert lurker_role == "lurker_or_observer", (
        f"expected lurker_or_observer for lurker actor, got {lurker_role!r}"
    )
    assert bot_role == "bot_or_automated_poster", (
        f"expected bot_or_automated_poster for bot actor, got {bot_role!r}"
    )
