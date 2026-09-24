# SPDX-License-Identifier: AGPL-3.0-or-later
"""list_actors / count_actors: per-actor counts, filters, and sorting."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.models.message import MessageTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _seed(storage: BaseRepository) -> tuple[UUID, UUID, UUID, UUID]:
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    g1 = await storage.upsert_group(
        source_id=src, platform_groupid="@g1", kind=GroupKind.CHAT, title="g1", seen_at=_NOW
    )
    g2 = await storage.upsert_group(
        source_id=src, platform_groupid="@g2", kind=GroupKind.CHAT, title="g2", seen_at=_NOW
    )
    alice = await storage.upsert_actor(
        source_id=src,
        actor_key="k:a",
        platform_userid="1",
        handle="@alice",
        display_name="A",
        seen_at=_NOW,
        is_bot=False,
    )
    bot = await storage.upsert_actor(
        source_id=src,
        actor_key="k:b",
        platform_userid="2",
        handle="@zbot",
        display_name="B",
        seen_at=_NOW,
        is_bot=True,
    )

    async def _msg(actor: UUID, gid: UUID, n: int) -> None:
        for i in range(n):
            await storage.put_message(
                MessageTable(
                    source_id=src,
                    group_id=gid,
                    actor_id=actor,
                    platform_msgid=f"{actor}-{i}",
                    evidence_ref=f"e:{actor}-{i}",
                    body="hi",
                    length_chars=2,
                    length_words=1,
                    sent_at_source=_NOW,
                    ingested_at=_NOW,
                )
            )

    await _msg(alice, g1, 3)
    await _msg(bot, g2, 1)
    return alice, bot, g1, g2


async def test_counts_per_actor(storage: BaseRepository) -> None:
    alice, bot, _, _ = await _seed(storage)
    got = {a.id: (mc, oc) for a, mc, oc in await storage.list_actors(limit=50)}
    assert got[alice] == (3, 0)
    assert got[bot] == (1, 0)


async def test_filter_is_bot(storage: BaseRepository) -> None:
    _, bot, _, _ = await _seed(storage)
    rows = await storage.list_actors(limit=50, is_bot=True)
    assert [a.id for a, _, _ in rows] == [bot]
    assert await storage.count_actors(is_bot=True) == 1
    assert await storage.count_actors(is_bot=False) == 1


async def test_filter_group_and_min_messages(storage: BaseRepository) -> None:
    alice, _, g1, g2 = await _seed(storage)
    assert [a.id for a, _, _ in await storage.list_actors(limit=50, group_id=g1)] == [alice]
    assert await storage.count_actors(group_id=g2) == 1
    assert [a.id for a, _, _ in await storage.list_actors(limit=50, min_messages=2)] == [alice]
    assert await storage.count_actors(min_messages=2) == 1


async def test_sort_by_messages_desc(storage: BaseRepository) -> None:
    alice, bot, _, _ = await _seed(storage)
    ordered = [a.id for a, _, _ in await storage.list_actors(limit=50, sort="messages")]
    assert ordered == [alice, bot]  # 3 msgs before 1


async def test_sort_by_handle(storage: BaseRepository) -> None:
    await _seed(storage)
    ordered = [a.current_handle for a, _, _ in await storage.list_actors(limit=50, sort="handle")]
    assert ordered == ["@alice", "@zbot"]
