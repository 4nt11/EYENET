# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum backfill page cursor: resume, latch-complete, then page-1-only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.forum.real import MyBBForumCollector
from eyenet.contracts.enums import SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.storage.factory import get_repository

_FIXTURE = (Path(__file__).resolve().parents[2] / "fixtures" / "mybb_thread.html").read_text(
    encoding="utf-8"
)
_SLUG = "Forum-Databases"
# Page 1 advertises 3 pages via the pagination block; each page links one thread.
_PAGE1 = (
    "<html><body>"
    "<a class='pagination_last' href='Forum-Databases?page=3'>3</a>"
    "<tr class='inline_row'><a href='Thread-p1--1'>x</a></tr>"
    "</body></html>"
)
_PAGE2 = "<html><body><tr class='inline_row'><a href='Thread-p2--2'>x</a></tr></body></html>"
_PAGE3 = "<html><body><tr class='inline_row'><a href='Thread-p3--3'>x</a></tr></body></html>"


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


def _client(seen: list[str | None]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        page = request.url.params.get("page")
        if path == f"/{_SLUG}":
            seen.append(page)  # None for page 1 (no ?page=), else "2"/"3"
            if page in (None, "1"):
                return httpx.Response(200, text=_PAGE1)
            if page == "2":
                return httpx.Response(200, text=_PAGE2)
            if page == "3":
                return httpx.Response(200, text=_PAGE3)
        if "Thread-" in path:
            return httpx.Response(200, text=_FIXTURE)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://forum.test")


async def _wire(tmp_path: Path, seen: list[str | None]):
    storage = get_repository(in_memory=True)
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=now)
    coll = MyBBForumCollector(
        bus=MemoryBus(),
        storage=storage,
        pool=_pool(tmp_path),
        identity_name="df",
        http_client=_client(seen),
    )
    coll._source_uuid = sid
    coll._board = "forum.test"
    coll._delay_min = coll._delay_max = 0.0
    return storage, coll, sid


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_skips_already_backfilled_pages(tmp_path: Path) -> None:
    seen: list[str | None] = []
    storage, coll, sid = await _wire(tmp_path, seen)
    # Pretend pages 1-2 are already done; resume at page 3.
    await storage.set_forum_crawl_cursor(
        source_id=sid,
        category_platform_groupid=_SLUG,
        next_page=3,
        backfill_complete=False,
        updated_at=datetime.now(tz=UTC),
    )

    await coll._crawl_category(_SLUG)

    # Page 1 (always) + page 3 (resume) fetched; page 2 was NOT re-scraped.
    assert None in seen  # page 1
    assert "3" in seen
    assert "2" not in seen
    # Reaching the last page latches complete.
    assert await storage.get_forum_crawl_cursor(source_id=sid, category_platform_groupid=_SLUG) == (
        4,
        True,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_category_is_page1_only(tmp_path: Path) -> None:
    seen: list[str | None] = []
    storage, coll, sid = await _wire(tmp_path, seen)
    await storage.set_forum_crawl_cursor(
        source_id=sid,
        category_platform_groupid=_SLUG,
        next_page=4,
        backfill_complete=True,
        updated_at=datetime.now(tz=UTC),
    )

    await coll._crawl_category(_SLUG)

    # Only page 1 touched; deep pages left alone once backfill is done.
    assert seen == [None]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_full_backfill_from_scratch_latches_complete(tmp_path: Path) -> None:
    seen: list[str | None] = []
    storage, coll, sid = await _wire(tmp_path, seen)

    await coll._crawl_category(_SLUG)

    # No prior cursor -> walks 1,2,3 and finishes.
    assert seen == [None, "2", "3"]
    assert await storage.get_forum_crawl_cursor(source_id=sid, category_platform_groupid=_SLUG) == (
        4,
        True,
    )
