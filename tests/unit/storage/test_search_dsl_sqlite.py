# SPDX-License-Identifier: AGPL-3.0-or-later
"""Query-DSL compiler — SQLite-impl probe (GLOBAL_SEARCH.md §9).

Seeds a small corpus, backfills ``search_document``, then asserts the neutral DSL
(AND/OR/NOT, ``==``/``!=``/``=~``/``:``, field scoping) compiles to the right result
set and that values stay BOUND (no injection), per §9.4."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.models import MessageTable
from eyenet.search_indexer.backfill import backfill_search
from eyenet.storage.factory import get_repository
from eyenet.storage.query import UnknownFieldError
from eyenet.storage.repository import BaseRepository
from tests._seed import seed_telegram_fixture

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 6, tzinfo=UTC)


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> BaseRepository:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    return get_repository(in_memory=True)


async def _seed(storage: BaseRepository) -> None:
    src, group_id, _a = await seed_telegram_fixture(
        storage, [{"actor_key": "seed", "platform_msgid": "0", "body": "unrelated seed"}], _NOW
    )
    zfo, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="k_zfo",
        platform_userid="zfo",
        handle="zfo",
        display_name="zfo",
        seen_at=_NOW,
    )
    pampa, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="k_pampa",
        platform_userid="lapampa",
        handle="lapampa",
        display_name="lapampa",
        seen_at=_NOW,
    )

    async def _msg(actor, pid, body):
        await storage.put_message(
            MessageTable(
                source_id=src,
                group_id=group_id,
                actor_id=actor,
                platform_msgid=pid,
                evidence_ref=f"m:{pid}",
                body=body,
                length_chars=len(body),
                length_words=len(body.split()),
                sent_at_source=_NOW,
                ingested_at=_NOW,
            ),
            [],
        )

    await _msg(zfo, "1", "today i leak the santiago database")
    await _msg(pampa, "2", "thanks for the santiago share")
    await backfill_search(storage)


async def _ids(storage: BaseRepository, q: str, **kw) -> set:
    rows = await storage.search_global(q, limit=50, **kw)
    return {(r.entity_type, r.fields.get("author") if r.fields else None) for r in rows}


@pytest.mark.asyncio
async def test_field_equals_scopes_to_author_and_type(storage: BaseRepository) -> None:
    await _seed(storage)
    rows = await storage.search_global("message.author == zfo", limit=50)
    assert len(rows) == 1
    assert rows[0].entity_type == "message"
    assert rows[0].fields["author"] == "zfo"
    await storage.close()


@pytest.mark.asyncio
async def test_boolean_and_or_not(storage: BaseRepository) -> None:
    await _seed(storage)
    # santiago appears in BOTH leak messages
    assert len(await storage.search_global("message.content : santiago", limit=50)) == 2
    # AND narrows to the one santiago message by zfo
    rows = await storage.search_global("santiago AND message.author == zfo", limit=50)
    assert {r.fields["author"] for r in rows} == {"zfo"}
    # OR unions the two authors
    rows = await storage.search_global(
        "message.author == zfo OR message.author == lapampa", limit=50
    )
    assert {r.fields["author"] for r in rows} == {"zfo", "lapampa"}
    # != excludes zfo's message (the other santiago message remains)
    rows = await storage.search_global("santiago AND message.author != zfo", limit=50)
    assert {r.fields["author"] for r in rows} == {"lapampa"}
    await storage.close()


@pytest.mark.asyncio
async def test_like_operator_substring(storage: BaseRepository) -> None:
    await _seed(storage)
    # =~ is case-insensitive substring: "ZF" matches author "zfo"
    rows = await storage.search_global("message.author =~ ZF", limit=50)
    assert {r.fields["author"] for r in rows} == {"zfo"}
    await storage.close()


@pytest.mark.asyncio
async def test_unknown_field_raises(storage: BaseRepository) -> None:
    with pytest.raises(UnknownFieldError):
        await storage.search_global("bogus.field == x", limit=50)
    await storage.close()


@pytest.mark.asyncio
async def test_injection_value_is_bound_not_executed(storage: BaseRepository) -> None:
    await _seed(storage)
    # A value crafted to break out of SQL must match nothing, not error or drop the table.
    evil = "zfo'); DROP TABLE search_document;--"
    rows = await storage.search_global(f'message.author == "{evil}"', limit=50)
    assert rows == []
    # table still intact + normal query still works
    assert len(await storage.search_global("message.author == zfo", limit=50)) == 1
    await storage.close()


@pytest.mark.asyncio
async def test_bad_syntax_degrades_to_text_search(storage: BaseRepository) -> None:
    await _seed(storage)
    # a dangling/garbled query must not 500 — it falls back to a plain text search
    rows = await storage.search_global("santiago AND", limit=50)
    assert len(rows) >= 2  # both santiago messages still found
    await storage.close()
