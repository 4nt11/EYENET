"""Unit tests for SQLiteMessageStore.put_message."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from eyenet.contracts.enums import AttachmentKind, GroupKind, SourceKind
from eyenet.models import AttachmentTable, MessageTable
from eyenet.models._base import new_uuid7
from eyenet.storage.actors import upsert_actor, upsert_group, upsert_source
from eyenet.storage.engines import StoreName, create_all_for, open_in_memory_engine
from eyenet.storage.messages import SQLiteMessageStore

_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Engine:
    e = open_in_memory_engine()
    create_all_for(StoreName.MESSAGES, e)
    return e


@pytest.fixture
def fk_ids(engine: Engine) -> tuple[UUID, UUID, UUID]:
    with Session(engine) as session:
        source_id = upsert_source(
            session, kind=SourceKind.TELEGRAM, display_name="tg:test", created_at=_NOW
        )
        group_id = upsert_group(
            session,
            source_id=source_id,
            platform_groupid="-100",
            kind=GroupKind.CHAT,
            title="Test",
            seen_at=_NOW,
        )
        actor_id = upsert_actor(
            session,
            source_id=source_id,
            actor_key="actor:" + "a" * 64,
            platform_userid="1",
            handle=None,
            display_name=None,
            seen_at=_NOW,
        )
        session.commit()
    return source_id, group_id, actor_id


@pytest.fixture
def store(engine: Engine) -> SQLiteMessageStore:
    return SQLiteMessageStore(engine)


def _make_row(
    source_id: UUID, group_id: UUID, actor_id: UUID, ref: str = "telegram:-100:1"
) -> MessageTable:
    return MessageTable(
        id=new_uuid7(),
        source_id=source_id,
        group_id=group_id,
        actor_id=actor_id,
        platform_msgid="1",
        evidence_ref=ref,
        body="hello world",
        length_chars=11,
        length_words=2,
        sent_at_source=_NOW,
        ingested_at=_NOW,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_message_writes_row(
    store: SQLiteMessageStore, fk_ids: tuple[UUID, UUID, UUID]
) -> None:
    source_id, group_id, actor_id = fk_ids
    row = _make_row(source_id, group_id, actor_id)
    result = await store.put_message(row)
    assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_by_evidence_ref_after_put(
    store: SQLiteMessageStore, fk_ids: tuple[UUID, UUID, UUID]
) -> None:
    source_id, group_id, actor_id = fk_ids
    row = _make_row(source_id, group_id, actor_id)
    await store.put_message(row)
    body = await store.get_by_evidence_ref(row.evidence_ref)
    assert body == b"hello world"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_duplicate_returns_false(
    store: SQLiteMessageStore, fk_ids: tuple[UUID, UUID, UUID]
) -> None:
    source_id, group_id, actor_id = fk_ids
    row = _make_row(source_id, group_id, actor_id)
    await store.put_message(row)
    # Same evidence_ref → duplicate
    row2 = _make_row(source_id, group_id, actor_id)
    result = await store.put_message(row2)
    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_message_with_attachment(engine: Engine, fk_ids: tuple[UUID, UUID, UUID]) -> None:
    source_id, group_id, actor_id = fk_ids
    store = SQLiteMessageStore(engine)
    row = _make_row(source_id, group_id, actor_id, ref="telegram:-100:2")
    row.has_attachment = True
    att = AttachmentTable(
        id=new_uuid7(),
        message_id=row.id,
        kind=AttachmentKind.IMAGE,
        mime="image/jpeg",
        size_bytes=1024,
        sha256="a" * 64,
        filename="photo.jpg",
        storage_uri=None,
    )
    result = await store.put_message(row, [att])
    assert result is True
