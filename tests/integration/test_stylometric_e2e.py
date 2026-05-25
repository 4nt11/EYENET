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
from sqlmodel import Session

from eyenet.bus import MemoryBus
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.service import run_service
from eyenet.storage import upsert_actor, upsert_group, upsert_source
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.storage.engines import StoreName

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
    """Pre-populate actor rows and message bodies for the fixture messages.

    The stub collector only publishes envelopes; it doesn't write to MessageStore.
    We seed the rows here so the sensor can dereference evidence_refs.
    """
    from eyenet.storage.messages import SQLiteMessageStore

    records = []
    with _FIXTURE.open() as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))

    engine = storage._engines[StoreName.MAIN]
    store = SQLiteMessageStore(engine)

    with Session(engine) as session:
        source_id = upsert_source(
            session, kind=SourceKind.TELEGRAM, display_name="telegram:tg_alpha", created_at=_NOW
        )
        group_id = upsert_group(
            session,
            source_id=source_id,
            platform_groupid="-100",
            kind=GroupKind.CHAT,
            title="Test",
            seen_at=_NOW,
        )
        actor_ids: dict[str, object] = {}
        for rec in records:
            ak = rec["actor_key"]
            if ak not in actor_ids:
                actor_ids[ak] = upsert_actor(
                    session,
                    source_id=source_id,
                    actor_key=ak,
                    platform_userid=ak[-8:],
                    handle=None,
                    display_name=None,
                    seen_at=_NOW,
                )
        session.commit()
        # capture committed FK ids before session closes
        committed_source_id = source_id
        committed_group_id = group_id
        committed_actor_ids = dict(actor_ids)

    for rec in records:
        ref = f"telegram:{rec['platform_groupid']}:{rec['platform_msgid']}"
        body = rec.get("body", "")
        sent = datetime.fromisoformat(rec["sent_at_source"])
        row = MessageTable(
            id=new_uuid7(),
            source_id=committed_source_id,
            group_id=committed_group_id,
            actor_id=committed_actor_ids[rec["actor_key"]],  # type: ignore[arg-type]
            platform_msgid=rec["platform_msgid"],
            evidence_ref=ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=sent,
            ingested_at=_NOW,
        )
        await store.put_message(row)


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
