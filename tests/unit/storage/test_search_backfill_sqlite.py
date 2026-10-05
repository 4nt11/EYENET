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
            {"actor_key": "k_poster", "platform_msgid": "1",
             "body": "today i leak this db, get it on my telegram https://t.me/zfoleaks"},
            {"actor_key": "k_other", "platform_msgid": "2", "body": "thanks for the share"},
        ],
        _NOW,
    )
    # an actor whose handle IS the query
    await storage.upsert_actor(
        source_id=source_id, actor_key="k_zfo", platform_userid="zfo",
        handle="zfo", display_name="zfo", seen_at=_NOW,
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
