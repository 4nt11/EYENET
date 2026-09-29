# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator-triggered reply-to-unlock: enqueue -> collector posts -> re-fetch updates."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.forum.real import MyBBForumCollector
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_REPLY_FORM = (
    '<form action="newreply.php?tid=42&processed=1" method="post">'
    '<input type="hidden" name="my_post_key" value="key123" />'
    '<input type="hidden" name="posthash" value="hash456" />'
    '<input type="hidden" name="tid" value="42" />'
    '<input type="hidden" name="subject" value="RE: leak" />'
    '<textarea name="message"></textarea></form>'
)
_UNLOCKED = (
    "<html><head><title>Leak thread</title></head><body>"
    '<div class="post classic" id="post_1001">'
    '<div class="post_user-profile"><a href="User-alice">alice</a></div>'
    '<span class="post_date">01-02-26, 09:30 AM</span>'
    '<div class="post_body">UNLOCKED: secret dump download link here</div></div>'
    "</body></html>"
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


def _client(seen: list[tuple[str, str]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        seen.append((method, path))
        if path == "/newreply.php" and method == "GET":
            return httpx.Response(200, text=_REPLY_FORM)
        if path == "/newreply.php" and method == "POST":
            return httpx.Response(200, text="<html><body>Thank you for your post</body></html>")
        if path == "/showthread.php":
            return httpx.Response(200, text=_UNLOCKED)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://forum.test")


async def _seed_gated(storage: BaseRepository, sid: UUID, gid: UUID) -> None:
    now = datetime.now(tz=UTC)
    aid = await storage.upsert_actor(
        source_id=sid,
        actor_key="actor:a",
        platform_userid="forum.test|alice",
        handle="alice",
        display_name="alice",
        seen_at=now,
    )
    await storage.put_message(
        MessageTable(
            id=new_uuid7(),
            source_id=sid,
            group_id=gid,
            actor_id=aid,
            platform_msgid="1001",
            evidence_ref="forum:forum.test:42:1001",
            body="You must reply to this thread to view this content",
            length_chars=10,
            length_words=2,
            sent_at_source=now,
            ingested_at=now,
            has_attachment=False,
            source_specific={"reply_gated": True, "body_html": "<gate>"},
        ),
        [],
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reply_posts_and_unlocks(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=now)
    gid = await storage.upsert_group(
        source_id=sid, platform_groupid="42", kind=GroupKind.FORUM_THREAD, title="t", seen_at=now
    )
    await _seed_gated(storage, sid, gid)
    await storage.create_forum_reply_request(
        source_id=sid,
        group_id=gid,
        message="thanks, appreciated",
        requested_by="op1",
        requested_at=now,
    )

    seen: list[tuple[str, str]] = []
    async with _client(seen) as client:
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
        await coll._process_reply_requests()

    # It scraped the form (GET), posted (POST), then re-fetched (showthread GET).
    assert ("GET", "/newreply.php") in seen
    assert ("POST", "/newreply.php") in seen
    assert ("GET", "/showthread.php") in seen
    # Request completed.
    assert await storage.list_pending_forum_reply_requests(sid) == []
    # The gated placeholder was overwritten in place with the unlocked content.
    msgs = await storage.messages_for_group(gid, limit=10)
    assert len(msgs) == 1
    assert "UNLOCKED" in msgs[0].body
    assert msgs[0].source_specific["reply_gated"] is False

    await storage.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_control_marks_failed_not_double_post(tmp_path: Path) -> None:
    storage = get_repository(in_memory=True)
    now = datetime.now(tz=UTC)
    sid = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=now)
    gid = await storage.upsert_group(
        source_id=sid, platform_groupid="42", kind=GroupKind.FORUM_THREAD, title="t", seen_at=now
    )
    await _seed_gated(storage, sid, gid)
    await storage.create_forum_reply_request(
        source_id=sid, group_id=gid, message="thanks", requested_by="op1", requested_at=now
    )

    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/newreply.php" and request.method == "GET":
            return httpx.Response(200, text=_REPLY_FORM)
        if request.url.path == "/newreply.php" and request.method == "POST":
            posts.append("x")
            return httpx.Response(200, text="<html>You must wait 30 seconds between posts.</html>")
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://forum.test"
    ) as client:
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
        await coll._process_reply_requests()
        # A second tick must NOT re-post (request is no longer pending -> no double post).
        await coll._process_reply_requests()

    assert len(posts) == 1  # posted once, flood -> failed, never retried automatically
    assert await storage.list_pending_forum_reply_requests(sid) == []

    await storage.close()
