# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum discovery: crawl only operator-monitored categories (fail-closed)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.forum.real import MyBBForumCollector
from eyenet.contracts.enums import GroupKind, JoinedVia, SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_FIXTURE = (Path(__file__).resolve().parents[2] / "fixtures" / "mybb_thread.html").read_text(
    encoding="utf-8"
)
_INDEX = (
    "<html><body><a href='member.php?action=logout'>Logout</a>"
    "<a href='Forum-Databases'>Databases</a>"
    "<a href='Forum-Fortnite'>Fortnite Methods</a></body></html>"
)
_DATABASES = (
    "<html><body><table><tr class='inline_row'>"
    "<a href='Thread-leak--1'>x</a></tr></table></body></html>"
)
_FORTNITE = (
    "<html><body><tr class='inline_row'><a href='Thread-fortnite--9'>x</a></tr></body></html>"
)


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


def _client(seen: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path == "/":
            return httpx.Response(200, text=_INDEX)
        if path == "/Forum-Databases":
            return httpx.Response(200, text=_DATABASES)
        if path == "/Forum-Fortnite":
            return httpx.Response(200, text=_FORTNITE)
        if "Thread-" in path:
            return httpx.Response(200, text=_FIXTURE)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://forum.test")


async def _monitor_category(storage: BaseRepository, sid, coll_id, slug: str):
    now = datetime.now(tz=UTC)
    cand = await storage.ensure_candidate(
        source_id=sid, platform_groupid=slug, seen_at=now, kind=GroupKind.FORUM_CATEGORY
    )
    gid = await storage.upsert_group(
        source_id=sid, platform_groupid=slug, kind=GroupKind.FORUM_CATEGORY, title=slug, seen_at=now
    )
    await storage.open_membership(
        collector_id=coll_id,
        group_id=gid,
        joined_at=now,
        joined_via=JoinedVia.CANDIDATE,
        joined_via_candidate_id=cand.id,
    )


async def _wire(tmp_path: Path, seen: list[str], monitor: bool):
    storage = get_repository(in_memory=True)
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=now)
    ident = await storage.create_identity(name="df", source_id=sid, session_path="/x")
    coll = await storage.create_collector(
        instance_name="collector-df",
        kind=SourceKind.FORUM,
        source_id=sid,
        identity_id=ident.id,
        config={},
        created_at=now,
        created_by_user_id=ident.id,
    )
    if monitor:
        await _monitor_category(storage, sid, coll.id, "Forum-Databases")

    bus = MemoryBus()
    captured: list[bytes] = []

    async def _rec(_s: str, p: bytes, _h: dict[str, str]) -> None:
        captured.append(p)

    await bus.subscribe("raw.message.>", _rec)

    coll_obj = MyBBForumCollector(
        bus=bus,
        storage=storage,
        pool=_pool(tmp_path),
        identity_name="df",
        http_client=_client(seen),
    )
    # White-box: skip on_subscribe's resolve/scan; pin the crawl state directly.
    coll_obj._source_uuid = sid
    coll_obj._collector_id = coll.id
    coll_obj._board = "forum.test"
    coll_obj._delay_min = coll_obj._delay_max = 0.0
    return storage, coll_obj, captured


@pytest.mark.unit
@pytest.mark.asyncio
async def test_monitored_category_crawled_unmonitored_skipped(tmp_path: Path) -> None:
    seen: list[str] = []
    storage, coll, captured = await _wire(tmp_path, seen, monitor=True)

    await coll.tick()

    # Monitored category was crawled and its thread ingested (2 posts -> 2 envelopes).
    assert "/Forum-Databases" in seen
    assert len(captured) == 2
    env = RawMessageEnvelope.model_validate_json(captured[0])
    assert env.source == SourceKind.FORUM
    assert env.platform_groupid == "1"  # thread tid from Thread-leak--1
    # Fail-closed: the un-monitored Fortnite category was NEVER fetched.
    assert "/Forum-Fortnite" not in seen
    assert not any("fortnite" in s.lower() for s in seen)

    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_membership_crawls_nothing(tmp_path: Path) -> None:
    seen: list[str] = []
    storage, coll, captured = await _wire(tmp_path, seen, monitor=False)

    await coll.tick()

    # Nothing monitored -> discovery yields nothing -> no category fetched, no posts.
    assert captured == []
    assert not any(s.startswith("/Forum-") for s in seen)

    await storage.close()
