# SPDX-License-Identifier: AGPL-3.0-or-later
"""SearchIndexerService handlers — SQLite-impl probe.

Drives the reindex handlers directly (envelope -> reindex -> FTS upsert) against a
seeded in-memory repo, so the live path is covered without a NATS broker. The
on_subscribe wiring is exercised separately by the e2e NATS smoke.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext
from eyenet.contracts.enums import InfrastructureKind, SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.contracts.search_events import SUBJECT_ACTOR_CHANGED, EntityChangedEnvelope
from eyenet.search_indexer.service import SearchIndexerService
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.propagation import ZERO_TRACEPARENT
from tests._seed import seed_telegram_fixture

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


def _tc() -> TraceContext:
    return TraceContext(traceparent=ZERO_TRACEPARENT)


@pytest.mark.asyncio
async def test_indexer_reindexes_actor_and_message(storage: BaseRepository) -> None:
    src, _gid, _actors = await seed_telegram_fixture(
        storage,
        [{"actor_key": "k1", "platform_msgid": "1", "body": "leak at t.me/zfoleaks now"}],
        _NOW,
    )
    actor_id, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="kz",
        platform_userid="zfo",
        handle="zfo",
        display_name="zfo",
        seen_at=_NOW,
    )
    svc = SearchIndexerService(bus=MemoryBus(), storage=storage)

    # entity.actor.changed -> actor indexed
    actor_env = EntityChangedEnvelope(
        entity_type="actor", entity_id=actor_id, source_id=src, trace_context=_tc()
    )
    await svc._handle_entity(actor_env.model_dump_json().encode())
    assert len(await storage.search_global("zfo", types=["actor"], limit=5)) == 1

    # raw.message -> message indexed (handles trigram catches 'zfo' in 'zfoleaks')
    msg_env = RawMessageEnvelope(
        source=SourceKind.TELEGRAM,
        instance_id="abcd1234",
        evidence_ref="telegram:-100:1",
        actor_key="k1",
        platform_groupid="-100",
        platform_msgid="1",
        sent_at_source=_NOW,
        collected_at=_NOW,
        length_chars=24,
        length_words=5,
        body_sha256="0" * 64,
        trace_context=_tc(),
    )
    await svc._handle_message(msg_env.model_dump_json().encode())
    msg_hits = await storage.search_global("zfoleaks", types=["message"], limit=5)
    assert len(msg_hits) == 1

    await storage.close()


@pytest.mark.asyncio
async def test_indexer_reindexes_artifact(storage: BaseRepository) -> None:
    artifact = await storage.put_infrastructure_artifact(
        kind=InfrastructureKind.WALLET_BTC,
        value="scamx-btc-live",
        first_seen_at_ingest=_NOW,
        last_seen_at_ingest=_NOW,
    )
    svc = SearchIndexerService(bus=MemoryBus(), storage=storage)
    env = EntityChangedEnvelope(
        entity_type="artifact", entity_id=artifact.id, trace_context=_tc()
    )
    await svc._handle_entity(env.model_dump_json().encode())
    hits = await storage.search_global("artifact.kind == wallet_btc", limit=5)
    assert len(hits) == 1
    assert hits[0].entity_id == artifact.id
    assert hits[0].kind == "wallet_btc"
    await storage.close()


@pytest.mark.asyncio
async def test_indexer_reindex_is_idempotent(storage: BaseRepository) -> None:
    src, _gid, _actors = await seed_telegram_fixture(
        storage, [{"actor_key": "k1", "platform_msgid": "1", "body": "hi"}], _NOW
    )
    actor_id, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="kz",
        platform_userid="zfo",
        handle="zfo",
        display_name="zfo",
        seen_at=_NOW,
    )
    svc = SearchIndexerService(bus=MemoryBus(), storage=storage)
    env = EntityChangedEnvelope(entity_type="actor", entity_id=actor_id, trace_context=_tc())
    await svc._handle_entity(env.model_dump_json().encode())
    await svc._handle_entity(env.model_dump_json().encode())
    assert await storage.count_search_global("zfo", types=["actor"]) == 1
    await storage.close()


@pytest.mark.asyncio
async def test_indexer_wiring_over_bus(storage: BaseRepository) -> None:
    """End-to-end over a real MemoryBus: on_subscribe -> published event -> index."""
    src, _gid, _actors = await seed_telegram_fixture(
        storage, [{"actor_key": "k1", "platform_msgid": "1", "body": "hi"}], _NOW
    )
    actor_id, _ = await storage.upsert_actor(
        source_id=src, actor_key="kz", platform_userid="zfo",
        handle="zfo", display_name="zfo", seen_at=_NOW,
    )
    bus = MemoryBus()
    svc = SearchIndexerService(bus=bus, storage=storage)
    await svc.on_subscribe()

    await BusEnvelopePublisher(bus).publish(
        SUBJECT_ACTOR_CHANGED,
        EntityChangedEnvelope(entity_type="actor", entity_id=actor_id, trace_context=_tc()),
    )
    # handlers schedule reindex via create_task; let the loop drain it
    for _ in range(20):
        await asyncio.sleep(0.01)
        if await storage.count_search_global("zfo", types=["actor"]) == 1:
            break
    assert await storage.count_search_global("zfo", types=["actor"]) == 1
    await storage.close()
