# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fail-closed on an unparseable post date: refuse the write + FAULT the collector.

A date we can't parse must NEVER become now() (false recency on an old leak —
the single most damaging field, CLAUDE.md 4a). The collector refuses the row and
halts rather than backfill garbage, and reports CollectorState.FAULTED so the
operator sees it and extends the parser.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.forum import ParsedPost
from eyenet.collectors.forum.real import MyBBForumCollector, UnparseableDateError
from eyenet.contracts.enums import CollectorState, SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


def _pool(tmp_path: Path) -> FileIdentityPool:
    entry = IdentityFileEntry(
        name="df",
        source=SourceKind.FORUM,
        cooldown_seconds=0,
        forum_base_url="https://forum.test",
        forum_delay_min=0.0,
        forum_delay_max=0.0,
    )
    cfg = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg)
    return FileIdentityPool(cfg, check_session_files=False)


async def _collector(tmp_path: Path, storage: BaseRepository) -> MyBBForumCollector:
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=now)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok")),
        base_url="https://forum.test",
    )
    coll = MyBBForumCollector(
        bus=MemoryBus(),
        storage=storage,
        pool=_pool(tmp_path),
        identity_name="df",
        http_client=client,
    )
    coll._source_uuid = sid
    coll._board = "forum.test"
    coll._delay_min = coll._delay_max = 0.0
    return coll


def _post(posted_raw: str) -> ParsedPost:
    return ParsedPost(
        pid="99",
        author_username="bob",
        author_display="bob",
        posted_at=None,  # the parser failed to read the date
        posted_raw=posted_raw,
        edited=False,
        body_text="leak dump here",
        body_html="<p>leak dump here</p>",
        reply_gated=False,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unparseable_date_refuses_write_and_raises(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    coll = await _collector(tmp_path, storage)

    with pytest.raises(UnparseableDateError) as ei:
        await coll._ingest_post("1234", "a leak", _post("13-45-9999 nonsense"), is_op=True)
    # the raw string rides the exception so the operator can extend the parser
    assert "13-45-9999 nonsense" in str(ei.value)

    # NOTHING was written — no now()-stamped row poisons the corpus.
    assert (
        await storage.resolve_message_id(
            source_id=coll._source_uuid, group_id=uuid4(), platform_msgid="99"
        )
        is None
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_date_span_also_raises(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    coll = await _collector(tmp_path, storage)
    with pytest.raises(UnparseableDateError):
        await coll._ingest_post("1234", "t", _post(""), is_op=False)  # date span missing


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tick_faults_and_halts_on_unparseable_date(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    coll = await _collector(tmp_path, storage)

    calls = {"n": 0}

    async def _boom() -> None:
        calls["n"] += 1
        raise UnparseableDateError(tid="t1", pid="99", raw="13-45-9999")

    coll._tick_body = _boom  # type: ignore[method-assign]

    await coll.tick()
    assert calls["n"] == 1
    assert coll._faulted is not None  # halted

    # FAULTED is visible on the health surface, carrying the reason.
    health = await coll.health()
    assert health.state is CollectorState.FAULTED
    assert health.last_error is not None and "13-45-9999" in health.last_error

    # Subsequent ticks are a no-op: no re-entry, no more board activity.
    await coll.tick()
    assert calls["n"] == 1  # _tick_body NOT called again
