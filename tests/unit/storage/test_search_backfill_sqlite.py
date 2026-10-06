# SPDX-License-Identifier: AGPL-3.0-or-later
"""Global-search backfill — SQLite-impl probe.

Pins ``EYENET_STORAGE_TYPE=sqlite`` + ``_sqlite`` suffix: exercises the FTS5
trigram/prose indexes the backfill populates. Seeds a small corpus, runs
``backfill_search``, and asserts cross-entity retrieval (the zfo/zfoleaks case).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import GroupKind
from eyenet.models import MessageTable
from eyenet.search_indexer.backfill import backfill_search
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from tests._seed import seed_telegram_fixture

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


async def _run(storage: BaseRepository) -> dict[str, int]:
    source_id, _group_id, _actors = await seed_telegram_fixture(
        storage,
        [
            {
                "actor_key": "k_poster",
                "platform_msgid": "1",
                "body": "today i leak this db, get it on my telegram https://t.me/zfoleaks",
            },
            {"actor_key": "k_other", "platform_msgid": "2", "body": "thanks for the share"},
        ],
        _NOW,
    )
    # an actor whose handle IS the query
    await storage.upsert_actor(
        source_id=source_id,
        actor_key="k_zfo",
        platform_userid="zfo",
        handle="zfo",
        display_name="zfo",
        seen_at=_NOW,
    )
    return await backfill_search(storage)


@pytest.mark.asyncio
async def test_backfill_indexes_and_finds_cross_entity(storage: BaseRepository) -> None:
    counts = await _run(storage)
    assert counts["actor"] >= 1
    assert counts["message"] == 2
    assert counts["group"] >= 1

    # actor handle hit
    actor_hits = await storage.search_global("zfo", types=["actor"], limit=10)
    assert any(getattr(h, "handles", "") and "zfo" in h.handles for h in actor_hits)

    # 'zfoleaks' is a full token in the message body -> prose match
    msg_hits = await storage.search_global("zfoleaks", types=["message"], limit=10)
    assert len(msg_hits) == 1

    # substring: 'zfo' matches 'zfoleaks' via the trigram handles index on the message
    sub_hits = await storage.search_global("zfo", limit=20)
    kinds = {h.entity_type for h in sub_hits}
    assert "actor" in kinds and "message" in kinds

    # facets
    facets = await storage.search_global_facets("zfo")
    assert facets["by_type"].get("actor", 0) >= 1

    await storage.close()


@pytest.mark.asyncio
async def test_backfill_is_idempotent(storage: BaseRepository) -> None:
    await _run(storage)
    first = await storage.count_search_global("zfo")
    # second run upserts the same rows, no duplicates
    await backfill_search(storage)
    second = await storage.count_search_global("zfo")
    assert first == second
    await storage.close()


@pytest.mark.asyncio
async def test_forum_thread_indexed_as_thread_with_op(storage: BaseRepository) -> None:
    """A forum thread indexes as entity_type='thread', enriched from its OP (the
    earliest post): author, creation date, full OP content, post count — and no
    stale 'group' doc is left behind."""
    source_id, _g, _a = await seed_telegram_fixture(
        storage, [{"actor_key": "k1", "platform_msgid": "1", "body": "seed"}], _NOW
    )
    tid, _ = await storage.upsert_group(
        source_id=source_id,
        platform_groupid="t-100",
        kind=GroupKind.FORUM_THREAD,
        title="IUEM database leak",
        seen_at=_NOW,
    )
    op_author, _ = await storage.upsert_actor(
        source_id=source_id,
        actor_key="k_op",
        platform_userid="leaker",
        handle="leaker",
        display_name="leaker",
        seen_at=_NOW,
    )
    replier, _ = await storage.upsert_actor(
        source_id=source_id,
        actor_key="k_reply",
        platform_userid="fan",
        handle="fan",
        display_name="fan",
        seen_at=_NOW,
    )
    op_time = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 2, tzinfo=UTC)
    # Insert the REPLY first to prove OP selection is by timestamp, not insert order.
    await storage.put_message(
        MessageTable(
            source_id=source_id,
            group_id=tid,
            actor_id=replier,
            platform_msgid="p2",
            evidence_ref="f:2",
            body="thanks bro",
            length_chars=10,
            length_words=2,
            sent_at_source=later,
            ingested_at=_NOW,
        ),
        [],
    )
    await storage.put_message(
        MessageTable(
            source_id=source_id,
            group_id=tid,
            actor_id=op_author,
            platform_msgid="p1",
            evidence_ref="f:1",
            body="Hey, leaking IUEM with 24k faces",
            length_chars=32,
            length_words=6,
            sent_at_source=op_time,
            ingested_at=_NOW,
        ),
        [],
    )

    counts = await backfill_search(storage)
    assert counts["thread"] == 1

    hits = await storage.search_global("IUEM", types=["thread"], limit=10)
    assert len(hits) == 1
    h = hits[0]
    assert h.entity_type == "thread"
    assert h.fields["thread_author"] == "leaker"  # OP author, not the replier
    assert h.fields["created"].startswith("2026-01-01")  # earliest post, not the reply
    assert "IUEM" in h.fields["op"]  # full OP content indexed
    assert h.fields["posts"] == 2

    # the thread must NOT also appear as a stale 'group' doc
    group_hits = await storage.search_global("IUEM", types=["group"], limit=10)
    assert all(hh.entity_id != tid for hh in group_hits)
    await storage.close()


@pytest.mark.asyncio
async def test_bulk_upsert_chunks_large_batch(storage: BaseRepository) -> None:
    """A single bulk call larger than the SQLite variable-cap chunk size lands
    every row (regression: 'too many SQL variables' on 90+ rows per INSERT)."""
    rows = [
        {
            "entity_type": "actor",
            "entity_id": uuid.uuid4(),
            "source_id": None,
            "status": None,
            "title": f"bulkactor{i}",
            "subtitle": None,
            "haystack": f"bulkactor{i} payload",
            "handles": f"bulkactor{i}",
        }
        for i in range(250)
    ]
    await storage.put_search_documents_bulk(rows)
    assert await storage.count_search_global("bulkactor", types=["actor"]) == 250
    await storage.close()
