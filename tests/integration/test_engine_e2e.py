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
from sqlmodel import Session, select

from eyenet.bus import MemoryBus
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.engine.engine import Engine
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.models.profile import ProfileTable
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.service import run_service
from eyenet.storage import SQLiteStorage, upsert_actor, upsert_group, upsert_source
from eyenet.storage.engines import StoreName
from eyenet.storage.messages import SQLiteMessageStore

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


async def _seed_messages(storage: SQLiteStorage) -> dict[str, UUID]:
    """Seed MessageTable rows with reply_to_msg_id set for lurker's reply messages.

    Two-pass: insert all messages first, then update reply FKs.
    Returns actor_key → actor_id mapping.
    """
    records: list[dict[str, Any]] = []
    with _FIXTURE.open() as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))

    messages_engine = storage._engines[StoreName.MAIN]
    store = SQLiteMessageStore(messages_engine)

    with Session(messages_engine) as session:
        source_id = upsert_source(
            session, kind=SourceKind.TELEGRAM, display_name="telegram:tg_alpha", created_at=_NOW
        )
        group_id = upsert_group(
            session,
            source_id=source_id,
            platform_groupid="-100",
            kind=GroupKind.CHAT,
            title="Test M3",
            seen_at=_NOW,
        )
        actor_ids: dict[str, UUID] = {}
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
        committed_source_id = source_id
        committed_group_id = group_id
        committed_actor_ids = dict(actor_ids)

    # Pass 1: insert all messages without reply_to_msg_id, record platform_msgid → UUID
    platform_to_uuid: dict[str, UUID] = {}
    for rec in records:
        body = rec.get("body", "")
        sent = datetime.fromisoformat(rec["sent_at_source"])
        msgid = rec["platform_msgid"]
        ref = f"telegram:-100:{msgid}"
        row = MessageTable(
            id=new_uuid7(),
            source_id=committed_source_id,
            group_id=committed_group_id,
            actor_id=committed_actor_ids[rec["actor_key"]],
            platform_msgid=msgid,
            evidence_ref=ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=sent,
            ingested_at=_NOW,
        )
        await store.put_message(row)
        platform_to_uuid[msgid] = row.id

    # Pass 2: set reply_to_msg_id for reply messages
    with Session(messages_engine) as session:
        for rec in records:
            reply_key = rec.get("reply_to_platform_msgid")
            if reply_key and reply_key in platform_to_uuid:
                ref = f"telegram:-100:{rec['platform_msgid']}"
                msg = session.exec(
                    select(MessageTable).where(MessageTable.evidence_ref == ref)
                ).first()
                if msg is not None:
                    msg.reply_to_msg_id = platform_to_uuid[reply_key]
                    session.add(msg)
        session.commit()

    return committed_actor_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_engine_e2e_role_signals(tmp_path: Path) -> None:
    """Full pipeline: fixture → bus → sensor → engine → ProfileStore.

    Asserts that both synthetic actors receive the expected role_signal.
    """
    pool = _pool(tmp_path)
    bus = MemoryBus()
    data_dir = tmp_path / "data"
    storage = SQLiteStorage(data_dir)

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
    def _get_role(actor_id: UUID) -> str | None:
        attribution_engine = storage._engines[StoreName.MAIN]
        with Session(attribution_engine) as session:
            row = session.exec(
                select(ProfileTable)
                .where(ProfileTable.actor_id == actor_id)
                .where(ProfileTable.is_current == True)  # noqa: E712
            ).first()
            return str(row.role_signal) if row and row.role_signal else None

    deadline = asyncio.get_event_loop().time() + 60.0
    while asyncio.get_event_loop().time() < deadline:
        lurker_role = _get_role(lurker_actor_id)
        bot_role = _get_role(bot_actor_id)
        if lurker_role is not None and bot_role is not None:
            break
        await asyncio.sleep(0.2)

    await collector.shutdown()
    await sensor.shutdown()
    await engine.shutdown()
    await asyncio.gather(sensor_task, engine_task, collector_task)
    await storage.close()

    lurker_role = _get_role(lurker_actor_id)
    bot_role = _get_role(bot_actor_id)

    assert lurker_role == "lurker_or_observer", (
        f"expected lurker_or_observer for lurker actor, got {lurker_role!r}"
    )
    assert bot_role == "bot_or_automated_poster", (
        f"expected bot_or_automated_poster for bot actor, got {bot_role!r}"
    )
