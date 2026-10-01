# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thread identity: a moved/re-slugged thread dedupes to its original via tid.

The thread PAGE carries the stable canonical tid; the alias binds tid -> first
group key, so a re-slugged copy resolves to the original key instead of forking a
new thread. Fallback (no tid on page) is slug-prefix normalization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from eyenet.bus import MemoryBus
from eyenet.collectors.forum.real import MyBBForumCollector, _normalize_thread_slug
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.models import GroupTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_FIXTURE = (Path(__file__).resolve().parents[2] / "fixtures" / "mybb_thread.html").read_text(
    encoding="utf-8"
)
# Same thread, two slugs (original in Databases, re-slugged after a move), both
# tid-less URLs but both pages expose the SAME canonical tid.
_ORIG = "Thread-DATABASE-UTEC-University-uruguay"
_MOVED = "Thread-UTEC-University-uruguay"
_TID = "520159"


def _thread_page() -> str:
    return f"<input type='hidden' name='tid' value='{_TID}'>" + _FIXTURE


def _client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "Thread-" in request.url.path:
            return httpx.Response(200, text=_thread_page())
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://forum.test")


async def _collector(tmp_path: Path, storage: BaseRepository):
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=now)
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
    coll = MyBBForumCollector(
        bus=MemoryBus(),
        storage=storage,
        pool=FileIdentityPool(cfg, check_session_files=False),
        identity_name="df",
        http_client=_client(),
    )
    coll._source_uuid = sid
    coll._board = "forum.test"
    coll._delay_min = coll._delay_max = 0.0
    return coll, sid


# -- the fallback helper (no network) ---------------------------------------


def test_normalize_strips_section_prefix() -> None:
    assert _normalize_thread_slug("Thread-DATABASE-UTEC-x") == "Thread-UTEC-x"
    assert _normalize_thread_slug("Thread-STEALER-LOGS-foo") == "Thread-foo"


def test_normalize_noop_on_tid_and_plain_slug() -> None:
    assert _normalize_thread_slug("520159") == "520159"  # numeric tid untouched
    assert _normalize_thread_slug("Thread-UTEC-x") == "Thread-UTEC-x"  # already normal


# -- the alias (storage, first-seen wins) -----------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_or_bind_first_seen_wins() -> None:
    storage = get_repository(in_memory=True)
    sid = await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="f", created_at=datetime.now(tz=UTC)
    )
    first = await storage.resolve_or_bind_forum_thread(
        source_id=sid, canonical_tid=_TID, fallback_platform_groupid=_ORIG
    )
    second = await storage.resolve_or_bind_forum_thread(
        source_id=sid, canonical_tid=_TID, fallback_platform_groupid=_MOVED
    )
    assert first == _ORIG
    assert second == _ORIG  # the re-slugged copy resolves to the original key


# -- the whole path (poll two slugs, one thread) ----------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_moved_thread_dedupes_to_original(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    coll, _sid = await _collector(tmp_path, storage)

    key_orig = await coll._poll_thread(_ORIG)
    key_moved = await coll._poll_thread(_MOVED)

    # Both polls land on the same stable key (the first-seen original slug).
    assert key_orig == _ORIG
    assert key_moved == _ORIG

    # Exactly ONE forum-thread group exists despite two different slugs polled.
    async with storage.session() as s:
        rows = list(
            await s.exec(select(GroupTable).where(GroupTable.kind == GroupKind.FORUM_THREAD))
        )
    assert [g.platform_groupid for g in rows] == [_ORIG]
