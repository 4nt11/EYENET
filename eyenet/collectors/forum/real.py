# SPDX-License-Identifier: AGPL-3.0-or-later
"""`MyBBForumCollector` - live MyBB forum collector over an imported cookie jar.

Poll-based, not event-based: each ``tick`` re-fetches the configured threads,
parses posts, and ingests the new ones. Login is NOT automated - the operator
logs into the board in a real browser once (solving the captcha by hand) and
exports the session cookies; this collector reuses that jar until it dies.

Session lifecycle:
- boot canary (``on_subscribe``): GET the board index; if the logged-in marker
  is absent the session is dead - emit a NEEDS_REAUTH syslog WARN. We do not try
  to re-login; a small operator re-exports the cookie jar by hand.
- ``put_message`` is idempotent on ``evidence_ref``, so re-polling a thread is
  safe: only genuinely new posts are written and published to the sensor.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse
from uuid import UUID

import httpx

from eyenet.collectors.base._credentials import materialize_forum_session
from eyenet.collectors.base.skeleton import CollectorSkeleton
from eyenet.collectors.forum import ParsedPost, parse_thread, thread_page_count
from eyenet.contracts._base import TraceContext
from eyenet.contracts.actor import actor_key
from eyenet.contracts.bus import Bus
from eyenet.contracts.enums import GroupKind, SourceKind, SystemLogLevel
from eyenet.contracts.identity_pool import IdentityPool
from eyenet.contracts.raw_message import RawMessageEnvelope, subject_for
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.logging import get_logger
from eyenet.telemetry.propagation import current_traceparent

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

    from eyenet.identity_pool.loader import IdentityFileEntry

_log = get_logger()

# ponytail: theme-cosmetic markers. A member session renders a logout link and
# the usercp; a guest gets a login form. If a custom theme renames these, the
# canary goes falsely-dead - upgrade to a stable per-board element then.
_LOGGED_IN_MARKERS = ("action=logout", "usercp")


def _zero_traceparent() -> str:
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


def _thread_id_from_url(url: str) -> str:
    """MyBB ``Thread-<slug>--<tid>`` -> ``<tid>``; fall back to the slug."""
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if "--" in slug:
        tail = slug.rsplit("--", 1)[-1]
        if tail.isdigit():
            return tail
    return slug


class MyBBForumCollector(CollectorSkeleton):
    """Cookie-session MyBB collector: fetch -> parse -> store -> publish."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        pool: IdentityPool,
        identity_name: str,
        session_key: Fernet | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name=identity_name,
            source_kind=SourceKind.FORUM,
        )
        # Decrypts the cookie jar at boot (DB pool). None + no injected client =
        # plaintext cookies.txt (file pool). An injected client is for tests
        # (httpx.MockTransport) and bypasses cookie materialization.
        self._session_key = session_key
        self._client = http_client
        self._owns_client = http_client is None
        self._source_uuid: UUID | None = None
        self._board = ""
        self._thread_urls: list[str] = []

    async def on_subscribe(self) -> None:
        await super().on_subscribe()
        entry = cast("IdentityFileEntry", self._claimed)
        self._board = urlparse(entry.forum_base_url or "").netloc or (entry.forum_base_url or "")
        self._thread_urls = list(entry.forum_thread_urls)

        if self._client is None:
            cookies = materialize_forum_session(entry, self._session_key)
            self._client = httpx.AsyncClient(
                base_url=entry.forum_base_url or "",
                cookies=cookies,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30.0,
                follow_redirects=True,
            )

        self._source_uuid = await self._storage.upsert_source(
            kind=SourceKind.FORUM,
            display_name=f"forum:{entry.name}",
            created_at=datetime.now(tz=UTC),
        )
        await self._check_session()

    async def stop(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        await super().stop()

    async def _check_session(self) -> bool:
        """Boot canary: is the imported cookie jar still logged in?"""
        if self._client is None:
            return False
        try:
            resp = await self._client.get("/")
        except httpx.HTTPError as exc:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.canary_unreachable",
                message=f"{self._identity_name}: board index unreachable ({exc!r})",
            )
            return False
        body = resp.text.lower()
        logged_in = any(marker in body for marker in _LOGGED_IN_MARKERS)
        if not logged_in:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.needs_reauth",
                message=(
                    f"{self._identity_name}: session cookie is dead; "
                    "re-export cookies.txt from a fresh browser login"
                ),
            )
        return logged_in

    async def tick(self) -> None:
        if self._client is None or self._source_uuid is None:
            return
        for url in self._thread_urls:
            await self._poll_thread(url)

    async def _poll_thread(self, url: str) -> None:
        client = self._client
        if client is None:
            return
        tid = _thread_id_from_url(url)
        try:
            first = await client.get(url)
            pages = thread_page_count(first.text)
            await self._ingest_page(tid, first.text)
            for page in range(2, pages + 1):
                resp = await client.get(url, params={"page": page})
                await self._ingest_page(tid, resp.text)
        except httpx.HTTPError as exc:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.fetch_failed",
                message=f"{self._identity_name}: {url} fetch failed ({exc!r})",
            )

    async def _ingest_page(self, tid: str, html: str) -> None:
        posts = parse_thread(html)
        if not posts:
            _log.warning(
                "forum.empty_page",
                identity=self._identity_name,
                thread=tid,
            )
            return
        for post in posts:
            await self._ingest_post(tid, post)

    async def _ingest_post(self, tid: str, post: ParsedPost) -> None:
        source_uuid = self._source_uuid
        if source_uuid is None:
            return
        now = datetime.now(tz=UTC)
        # Board-scope the userid: MyBB slugs collide across boards.
        platform_userid = f"{self._board}|{post.author_username}"
        key = actor_key(SourceKind.FORUM, platform_userid)
        # post_date is board-local NAIVE; assume board-UTC and fall back to now()
        # for a relative/unparsed date.
        # ponytail: swap the UTC assumption for the source's configured tz offset.
        sent_at = post.posted_at.replace(tzinfo=UTC) if post.posted_at is not None else now

        group_id = await self._storage.upsert_group(
            source_id=source_uuid,
            platform_groupid=tid,
            kind=GroupKind.FORUM_THREAD,
            title=None,
            seen_at=now,
        )
        actor_id = await self._storage.upsert_actor(
            source_id=source_uuid,
            actor_key=key,
            platform_userid=platform_userid,
            handle=post.author_display or None,
            display_name=post.author_display or None,
            seen_at=sent_at,
            is_bot=False,
        )

        evidence_ref = f"forum:{self._board}:{tid}:{post.pid}"
        body = post.body_text
        msg_row = MessageTable(
            id=new_uuid7(),
            source_id=source_uuid,
            group_id=group_id,
            actor_id=actor_id,
            platform_msgid=post.pid,
            evidence_ref=evidence_ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=sent_at,
            ingested_at=now,
            has_attachment=False,
            reply_to_msg_id=None,
            forward_of_msg_id=None,
            forward_origin_actor_id=None,
            # Keep the evidence-faithful markup + edited flag alongside the row.
            source_specific={"body_html": post.body_html, "edited": post.edited},
        )
        written = await self._storage.put_message(msg_row, [])

        # Only publish NEW posts: put_message is idempotent, so a re-poll of an
        # unchanged thread writes nothing and must not re-spam the sensor.
        if not written:
            return

        env = RawMessageEnvelope(
            source=SourceKind.FORUM,
            instance_id=self.instance_id,
            evidence_ref=evidence_ref,
            actor_key=key,
            platform_groupid=tid,
            platform_msgid=post.pid,
            sent_at_source=sent_at,
            collected_at=now,
            length_chars=len(body),
            length_words=len(body.split()),
            body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            is_forward=False,
            has_attachment=False,
            trace_context=TraceContext(traceparent=current_traceparent() or _zero_traceparent()),
        )
        await self.publisher.publish(subject_for(SourceKind.FORUM, self.instance_id), env)
        self._record_emission()
        _log.info(
            "forum.ingested",
            identity=self._identity_name,
            evidence_ref=evidence_ref,
            actor_key=key[:16],
        )


__all__ = ["MyBBForumCollector"]
