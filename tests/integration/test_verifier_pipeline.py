"""Integration: Linker proposes → Verifier promotes to SUSPECTED (MemoryBus).

M8 push-mode happy path. Two synthetic actors with bodies seeded into
the messages store; a LinkageProposedEnvelope on the bus drives the
Verifier's full corpus-dereference → registry-run → composite-score path.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlmodel import Session

from eyenet.bus import MemoryBus
from eyenet.cli.config import VerifierConfig, VerifierThresholds
from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_PROPOSED,
    SUBJECT_LINKAGE_SUSPECTED,
    LinkageProposedEnvelope,
    LinkageSuspectedEnvelope,
)
from eyenet.contracts.enums import GroupKind, LinkageState, SourceKind
from eyenet.models._base import new_uuid7
from eyenet.models.message import MessageTable
from eyenet.storage import SQLiteStorage, upsert_actor, upsert_group, upsert_source
from eyenet.storage.engines import StoreName
from eyenet.storage.messages import SQLiteMessageStore
from eyenet.verifier.service import VerifierService

_TC = TraceContext(traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01")
_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> SQLiteStorage:
    return SQLiteStorage(Path(tempfile.mkdtemp()))


async def _seed_corpus_async(
    storage: SQLiteStorage,
    bodies: list[str],
    *,
    msg_prefix: str,
) -> UUID:
    """Seed a synthetic actor with N bodies. Returns the actor_id assigned by upsert_actor."""
    engine = storage._engines[StoreName.MAIN]
    store = SQLiteMessageStore(engine)
    with Session(engine) as session:
        source_id = upsert_source(
            session,
            kind=SourceKind.TELEGRAM,
            display_name=f"telegram:{msg_prefix}",
            created_at=_NOW,
        )
        group_id = upsert_group(
            session,
            source_id=source_id,
            platform_groupid=f"-100-{msg_prefix}",
            kind=GroupKind.CHAT,
            title="test",
            seen_at=_NOW,
        )
        actor_id = upsert_actor(
            session,
            source_id=source_id,
            actor_key=f"actor:test:{msg_prefix}",
            platform_userid=msg_prefix,
            handle=None,
            display_name=None,
            seen_at=_NOW,
        )
        session.commit()
        committed_source_id = source_id
        committed_group_id = group_id

    for i, body in enumerate(bodies):
        ref = f"{msg_prefix}:-100:{i}"
        row = MessageTable(
            id=new_uuid7(),
            source_id=committed_source_id,
            group_id=committed_group_id,
            actor_id=actor_id,
            platform_msgid=f"{msg_prefix}-{i}",
            evidence_ref=ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=_NOW,
            ingested_at=_NOW,
        )
        await store.put_message(row)
    return actor_id


def _proposed(actor_a: UUID, actor_b: UUID, linkage_id: UUID) -> LinkageProposedEnvelope:
    a, b = sorted([actor_a, actor_b])
    return LinkageProposedEnvelope(
        linkage_id=linkage_id,
        actor_a_id=a,
        actor_b_id=b,
        method="test_method",
        score=0.5,
        evidence={"language": "es"},
        proposed_at=_NOW,
        trace_context=_TC,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_same_author_promoted_to_suspected(storage: SQLiteStorage) -> None:
    bus = MemoryBus()
    suspected: list[LinkageSuspectedEnvelope] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        suspected.append(LinkageSuspectedEnvelope.model_validate_json(payload))

    await bus.subscribe(SUBJECT_LINKAGE_SUSPECTED, _capture)

    body_set = [
        "hola que tal compita todo bien aca",
        "muy bien gracias por preguntar amigo",
        "che mira esto que esta pasando",
    ] * 25
    a1 = await _seed_corpus_async(storage, body_set, msg_prefix="a")
    a2 = await _seed_corpus_async(storage, body_set, msg_prefix="b")
    actor_a, actor_b = (a1, a2) if a1 < a2 else (a2, a1)

    # Seed a real PROPOSED linkage row so the transition has a target
    linkage = await storage.linkages.insert_proposed(
        actor_a, actor_b, "test_method", 0.5, {"language": "es"}
    )

    service = VerifierService(
        bus=bus,
        storage=storage,
        config=VerifierConfig(thresholds=VerifierThresholds(composite_floor=0.5)),
    )
    await service.on_subscribe()

    await bus.publish(
        SUBJECT_LINKAGE_PROPOSED,
        _proposed(actor_a, actor_b, linkage.id).model_dump_json().encode(),
    )
    await asyncio.sleep(0.4)

    assert len(suspected) == 1
    assert suspected[0].linkage_id == linkage.id
    assert suspected[0].decided_by == "verifier"

    # State machine: linkage row now SUSPECTED
    row = await storage.linkages.get(linkage.id)
    assert row is not None
    assert row.state == LinkageState.SUSPECTED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_diff_author_not_promoted(storage: SQLiteStorage) -> None:
    bus = MemoryBus()
    suspected: list[bytes] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        suspected.append(payload)

    await bus.subscribe(SUBJECT_LINKAGE_SUSPECTED, _capture)

    body_a = ["hello world how are you today friend good morning"] * 80
    body_b = ["hola estimado caballero gracias por venir esta noche"] * 80
    a1 = await _seed_corpus_async(storage, body_a, msg_prefix="a")
    a2 = await _seed_corpus_async(storage, body_b, msg_prefix="b")
    actor_a, actor_b = (a1, a2) if a1 < a2 else (a2, a1)

    linkage = await storage.linkages.insert_proposed(
        actor_a, actor_b, "test_method", 0.5, {"language": None}
    )

    service = VerifierService(
        bus=bus,
        storage=storage,
        # Composite floor 0.75 — well above what diff-author should produce
        config=VerifierConfig(thresholds=VerifierThresholds(composite_floor=0.75)),
    )
    await service.on_subscribe()

    await bus.publish(
        SUBJECT_LINKAGE_PROPOSED,
        _proposed(actor_a, actor_b, linkage.id).model_dump_json().encode(),
    )
    await asyncio.sleep(0.3)

    assert len(suspected) == 0
    row = await storage.linkages.get(linkage.id)
    assert row is not None
    assert row.state == LinkageState.PROPOSED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_short_corpus_skips_verifier(storage: SQLiteStorage) -> None:
    bus = MemoryBus()
    suspected: list[bytes] = []

    async def _capture(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        suspected.append(payload)

    await bus.subscribe(SUBJECT_LINKAGE_SUSPECTED, _capture)

    a1 = await _seed_corpus_async(storage, ["one"] * 5, msg_prefix="a")
    a2 = await _seed_corpus_async(storage, ["two"] * 5, msg_prefix="b")
    actor_a, actor_b = (a1, a2) if a1 < a2 else (a2, a1)

    linkage = await storage.linkages.insert_proposed(
        actor_a, actor_b, "test", 0.5, {"language": "es"}
    )

    service = VerifierService(bus=bus, storage=storage)
    await service.on_subscribe()

    await bus.publish(
        SUBJECT_LINKAGE_PROPOSED,
        _proposed(actor_a, actor_b, linkage.id).model_dump_json().encode(),
    )
    await asyncio.sleep(0.2)

    assert len(suspected) == 0
    # Linkage stays PROPOSED — verifier couldn't speak
    row = await storage.linkages.get(linkage.id)
    assert row is not None
    assert row.state == LinkageState.PROPOSED
