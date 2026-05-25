"""Unit tests for the flat-repo ``put_message`` (MessagesMixin)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.enums import AttachmentKind, GroupKind, SourceKind
from eyenet.models import AttachmentTable, MessageTable
from eyenet.models._base import new_uuid7
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
async def fk_ids(storage: BaseRepository) -> tuple[UUID, UUID, UUID]:
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg:test", created_at=_NOW
    )
    group_id = await storage.upsert_group(
        source_id=source_id,
        platform_groupid="-100",
        kind=GroupKind.CHAT,
        title="Test",
        seen_at=_NOW,
    )
    actor_id = await storage.upsert_actor(
        source_id=source_id,
        actor_key="actor:" + "a" * 64,
        platform_userid="1",
        handle=None,
        display_name=None,
        seen_at=_NOW,
    )
    return source_id, group_id, actor_id


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
    storage: BaseRepository, fk_ids: tuple[UUID, UUID, UUID]
) -> None:
    source_id, group_id, actor_id = fk_ids
    row = _make_row(source_id, group_id, actor_id)
    result = await storage.put_message(row)
    assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_by_evidence_ref_after_put(
    storage: BaseRepository, fk_ids: tuple[UUID, UUID, UUID]
) -> None:
    source_id, group_id, actor_id = fk_ids
    row = _make_row(source_id, group_id, actor_id)
    await storage.put_message(row)
    body = await storage.get_message_body(row.evidence_ref)
    assert body == b"hello world"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_duplicate_returns_false(
    storage: BaseRepository, fk_ids: tuple[UUID, UUID, UUID]
) -> None:
    source_id, group_id, actor_id = fk_ids
    row = _make_row(source_id, group_id, actor_id)
    await storage.put_message(row)
    row2 = _make_row(source_id, group_id, actor_id)
    result = await storage.put_message(row2)
    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_message_with_attachment(
    storage: BaseRepository, fk_ids: tuple[UUID, UUID, UUID]
) -> None:
    source_id, group_id, actor_id = fk_ids
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
    result = await storage.put_message(row, [att])
    assert result is True
