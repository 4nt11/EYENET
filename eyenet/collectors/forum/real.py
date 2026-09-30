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

import asyncio
import hashlib
import random
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy.exc import OperationalError

from eyenet.collectors.base._credentials import materialize_forum_session
from eyenet.collectors.base.skeleton import CollectorSkeleton, VisibleGroup
from eyenet.collectors.forum import (
    ParsedPost,
    parse_forum_links,
    parse_reply_form,
    parse_thread,
    parse_thread_links,
    parse_thread_title,
    thread_page_count,
)
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

# Not-stupid pacing defaults (seconds). Every request waits a jittered delay in
# [min, max]; requests are strictly sequential. A live board bans an account that
# rips flat-out, so these are deliberately browsing-speed, tunable per identity.
_DEFAULT_DELAY_MIN = 4.0
_DEFAULT_DELAY_MAX = 12.0
# One paced discovery sweep, then rest. Re-enumerating 500-page categories every
# minute would be its own DoS; a category rarely gains threads that fast.
_DEFAULT_DISCOVERY_INTERVAL = 21_600  # 6h
# 0 = walk every page of a category (full backfill). MyBB sorts threads by last
# post desc, so a positive cap gets the most recently active threads first.
_DEFAULT_MAX_CATEGORY_PAGES = 0
# Per-thread depth on a sweep. Page 1 is the leak + the OP (the signal + the
# actor worth scraping); deeper pages are leecher "thanks" that bloat the corpus.
# So default shallow for breadth; the operator backfills a specific thread deeper
# on demand (POST .../backfill). 0 = all pages.
_DEFAULT_MAX_THREAD_PAGES = 1


def _zero_traceparent() -> str:
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


def _reply_outcome(html: str) -> str:
    """Classify a MyBB do_newreply response: 'flood' | 'error' | 'ok'.

    Leans toward 'ok' on ambiguity ON PURPOSE: a false 'failed' would tempt a
    re-queue and double-post (a bot signature), whereas a false 'ok' just leaves
    the operator seeing still-gated content to re-try. So only an explicit flood
    or error page is a non-ok outcome.
    ponytail: text heuristic on MyBB's stock pages; a hard theme rewrite of these
    strings would need updating here.
    """
    t = html.lower()
    if "wait" in t and "second" in t and ("post" in t or "flood" in t):
        return "flood"
    if 'class="error"' in t or "did not enter a message" in t or "not allowed to post" in t:
        return "error"
    return "ok"


def _last_segment(url: str) -> str:
    return urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]


def _thread_id_from_url(url: str) -> str:
    """MyBB ``Thread-<slug>--<tid>`` -> ``<tid>``; fall back to the slug."""
    slug = _last_segment(url)
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
        self._collector_id: UUID | None = None
        self._board = ""
        self._thread_urls: list[str] = []
        # Pacing / discovery (overridden from the identity in on_subscribe).
        self._delay_min = _DEFAULT_DELAY_MIN
        self._delay_max = _DEFAULT_DELAY_MAX
        self._discovery_interval = float(_DEFAULT_DISCOVERY_INTERVAL)
        self._max_category_pages = _DEFAULT_MAX_CATEGORY_PAGES
        self._max_thread_pages = _DEFAULT_MAX_THREAD_PAGES
        # When we last swept (monotonic) + the monitored set that sweep was for
        # (so a newly-monitored category triggers a re-sweep next tick instead of
        # waiting out the interval).
        self._last_discovery = 0.0
        self._last_monitored: frozenset[str] = frozenset()

    async def on_subscribe(self) -> None:
        await super().on_subscribe()
        entry = cast("IdentityFileEntry", self._claimed)
        self._board = urlparse(entry.forum_base_url or "").netloc or (entry.forum_base_url or "")
        self._thread_urls = list(entry.forum_thread_urls)
        self._delay_min = float(getattr(entry, "forum_delay_min", _DEFAULT_DELAY_MIN))
        self._delay_max = float(getattr(entry, "forum_delay_max", _DEFAULT_DELAY_MAX))
        self._discovery_interval = float(
            getattr(entry, "forum_discovery_interval", _DEFAULT_DISCOVERY_INTERVAL)
        )
        self._max_category_pages = int(
            getattr(entry, "forum_max_category_pages", _DEFAULT_MAX_CATEGORY_PAGES)
        )
        self._max_thread_pages = int(
            getattr(entry, "forum_max_thread_pages", _DEFAULT_MAX_THREAD_PAGES)
        )

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
        # Our own collector row: the operator's monitored-category memberships are
        # keyed to it (list_active_memberships). Without it the monitor set stays
        # empty and we crawl nothing (fail-closed).
        collector = await self._storage.resolve_collector_by_instance_id(self.instance_id)
        self._collector_id = collector.id if collector is not None else None
        # Bind our row to the source we actually ingest into (the placeholder
        # source it was registered against has zero of our messages).
        await self._bind_collector_row_source(collector, self._source_uuid)
        # Populate /monitored-groups with the board's categories so the operator
        # can pick which to monitor. Read-only page fetch, nothing joined.
        if await self._check_session():
            await self.scan_visible_groups(source_id=self._source_uuid)

    async def stop(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
        await super().stop()

    async def _get(self, url: str, **kw: Any) -> httpx.Response:
        """Every board request funnels through here: sequential + jittered delay.

        This is the single choke point that keeps the collector browsing-speed.
        There is deliberately no un-throttled request path.
        """
        if self._client is None:  # pragma: no cover - guarded by callers
            raise RuntimeError("forum collector http client not initialized")
        await asyncio.sleep(random.uniform(self._delay_min, self._delay_max))  # noqa: S311 - jitter, not crypto
        return await self._client.get(url, **kw)

    async def _post(self, url: str, **kw: Any) -> httpx.Response:
        """Throttled POST — the ONLY write path, same jittered pacing as reads."""
        if self._client is None:  # pragma: no cover - guarded by callers
            raise RuntimeError("forum collector http client not initialized")
        await asyncio.sleep(random.uniform(self._delay_min, self._delay_max))  # noqa: S311 - jitter, not crypto
        return await self._client.post(url, **kw)

    async def enumerate_visible_groups(self) -> list[VisibleGroup]:
        """The board's categories (GroupKind.FORUM_CATEGORY) from the index.

        Read-only: fetches the index and lists forums. Monitoring one is a
        purely internal membership the operator opens by hand; nothing here (or
        anywhere in this collector) performs a forum-side join.
        """
        index = await self._get("/")
        out: list[VisibleGroup] = []
        for url in parse_forum_links(index.text):
            slug = _last_segment(url)
            out.append(
                VisibleGroup(
                    platform_groupid=slug,
                    kind=GroupKind.FORUM_CATEGORY,
                    title=slug.replace("Forum-", "").replace("-", " "),
                    is_member=True,
                )
            )
        return out

    async def _check_session(self) -> bool:
        """Boot canary: is the imported cookie jar still logged in?"""
        if self._client is None:
            return False
        try:
            resp = await self._get("/")
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
        # Operator-queued actions first, so they're prompt (still throttled).
        await self._process_reply_requests()
        await self._process_backfill_requests()
        # Re-sweep only when there is a reason to: first run, the monitored set
        # changed, or the interval elapsed. Reading the monitored set is a cheap
        # DB read; the paced HTTP sweep is gated behind it, so an idle collector
        # with nothing monitored makes ZERO board requests.
        now = time.monotonic()
        monitored = frozenset(await self._monitored_categories())
        if not (
            self._last_discovery == 0.0
            or monitored != self._last_monitored
            or (now - self._last_discovery) >= self._discovery_interval
        ):
            return
        self._last_monitored = monitored
        self._last_discovery = now
        # Manual thread pins first (few, fast).
        for url in self._thread_urls:
            await self._poll_thread(url)
        # Then each monitored category, INTERLEAVED: scrape each page's threads
        # as we discover them (newest-first on MyBB) so posts flow from the first
        # minute instead of after a full multi-hour enumeration.
        for slug in sorted(monitored):
            try:
                await self._crawl_category(slug)
            except OperationalError as exc:
                # A DB lock (SQLITE_BUSY past busy_timeout) on ONE category must not
                # abort the whole sweep and starve the others — that is exactly what
                # left "Stealer Logs" at 0 threads while "Databases" (swept first,
                # alphabetically) kept dying mid-crawl. Log this pass and move on;
                # the next tick retries the category from the top.
                await self.syslog(
                    level=SystemLogLevel.WARN,
                    event="forum.category_crawl_locked",
                    message=f"{self._identity_name}: {slug} DB-locked, skipping pass ({exc!r})",
                )

    async def _monitored_categories(self) -> list[str]:
        """Category slugs the operator chose to monitor (fail-closed if none).

        Purely a DB read of this collector's memberships; opening one is a
        manual operator action, never automatic.
        """
        if self._collector_id is None:
            return []
        slugs: list[str] = []
        for m in await self._storage.list_active_memberships(collector_id=self._collector_id):
            grp = await self._storage.get_group(m.group_id)
            if grp is not None and grp.kind == GroupKind.FORUM_CATEGORY:
                slugs.append(grp.platform_groupid)
        return slugs

    async def _crawl_category(self, slug: str) -> None:
        """Walk one MONITORED category newest-page-first, scraping as we go.

        Read-only. Each page's threads are polled immediately (interleaved), so
        the most recently active threads surface first and a huge category still
        streams posts from the start instead of after a full enumeration.
        """
        _log.info("forum.category_sweep_start", identity=self._identity_name, category=slug)
        page = 1
        last = 1
        threads = 0
        while True:
            try:
                resp = await self._get(slug, params={"page": page} if page > 1 else None)
            except httpx.HTTPError as exc:
                await self.syslog(
                    level=SystemLogLevel.WARN,
                    event="forum.category_fetch_failed",
                    message=f"{self._identity_name}: {slug} p{page} failed ({exc!r})",
                )
                return
            if page == 1:
                last = thread_page_count(resp.text)
                if self._max_category_pages > 0:
                    last = min(last, self._max_category_pages)
            for thread_url in parse_thread_links(resp.text):
                try:
                    if self._source_uuid is not None:
                        await self._storage.record_forum_thread_link(
                            source_id=self._source_uuid,
                            category_platform_groupid=slug,
                            thread_platform_groupid=_thread_id_from_url(thread_url),
                            seen_at=datetime.now(tz=UTC),
                        )
                    await self._poll_thread(thread_url)
                    threads += 1
                except OperationalError as exc:
                    # One thread hitting a DB lock shouldn't abort the whole category
                    # (and thus the sweep). Skip it; the category still finishes and
                    # the next tick re-polls. Newest-first ordering means a skip is
                    # re-picked-up promptly.
                    await self.syslog(
                        level=SystemLogLevel.WARN,
                        event="forum.thread_crawl_locked",
                        message=f"{self._identity_name}: {thread_url} DB-locked, skipped ({exc!r})",
                    )
            if page >= last:
                break
            page += 1
        _log.info(
            "forum.category_sweep_done",
            identity=self._identity_name,
            category=slug,
            threads=threads,
            pages=last,
        )

    async def _poll_thread(self, url: str) -> None:
        tid = _thread_id_from_url(url)
        try:
            first = await self._get(url)
            pages = thread_page_count(first.text)
            # Cap per-thread depth: the leak announcement + download live on page 1;
            # deep pages are "thanks for the share" noise. Capping gets breadth
            # (many threads' signal) instead of deep-mining a few. 0 = all pages.
            if self._max_thread_pages > 0:
                pages = min(pages, self._max_thread_pages)
            title = parse_thread_title(first.text)  # subject from page 1, reused for all pages
            await self._ingest_page(tid, title, first.text)
            for page in range(2, pages + 1):
                resp = await self._get(url, params={"page": page})
                await self._ingest_page(tid, title, resp.text)
        except httpx.HTTPError as exc:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.fetch_failed",
                message=f"{self._identity_name}: {url} fetch failed ({exc!r})",
            )

    # -- operator-triggered reply-to-unlock (write path) ----------------------

    async def _process_reply_requests(self) -> None:
        """Post the operator's queued replies, one at a time, under the throttle.

        Never automatic: each request was explicitly enqueued by the operator with
        their own typed message. We only execute what is already PENDING.
        """
        if self._source_uuid is None:
            return
        for req in await self._storage.list_pending_forum_reply_requests(self._source_uuid):
            await self._execute_reply(req)

    async def _execute_reply(self, req: Any) -> None:
        now = datetime.now(tz=UTC)
        grp = await self._storage.get_group(req.group_id)
        if grp is None:
            await self._storage.complete_forum_reply_request(
                req.id, state="failed", result="group_gone", completed_at=now
            )
            return
        tid = grp.platform_groupid
        try:
            # Scrape fresh single-use tokens from the reply form.
            form_page = await self._get("newreply.php", params={"tid": tid})
            form = parse_reply_form(form_page.text)
            if form is None:
                await self._storage.complete_forum_reply_request(
                    req.id,
                    state="failed",
                    result="no_reply_form (session may lack post permission)",
                    completed_at=now,
                )
                return
            resp = await self._post(
                "newreply.php",
                params={"tid": tid, "processed": "1"},
                data={
                    "my_post_key": form.my_post_key,
                    "posthash": form.posthash,
                    "subject": form.subject or f"RE: {tid}",
                    "tid": form.tid,
                    "action": "do_newreply",
                    "message": req.message,
                },
            )
        except httpx.HTTPError as exc:
            await self._storage.complete_forum_reply_request(
                req.id, state="failed", result=f"http_error:{exc!r}", completed_at=now
            )
            return

        outcome = _reply_outcome(resp.text)
        if outcome != "ok":
            await self._storage.complete_forum_reply_request(
                req.id,
                state="failed",
                result=f"{outcome} (re-queue to retry)",
                completed_at=now,
            )
            return

        await self._refetch_thread_unlocked(tid)
        await self._storage.complete_forum_reply_request(
            req.id, state="done", result="posted; thread re-fetched", completed_at=now
        )
        await self.syslog(
            level=SystemLogLevel.NOTICE,
            event="forum.reply_posted",
            message=f"{self._identity_name}: replied to unlock {tid} (op {req.requested_by})",
        )

    # -- operator-triggered deep backfill (read-only, one thread) --------------

    async def _process_backfill_requests(self) -> None:
        """Deep-fetch every page of the threads the operator queued for backfill."""
        if self._source_uuid is None:
            return
        for req in await self._storage.list_pending_forum_backfill_requests(self._source_uuid):
            await self._execute_backfill(req)

    async def _execute_backfill(self, req: Any) -> None:
        now = datetime.now(tz=UTC)
        grp = await self._storage.get_group(req.group_id)
        if grp is None:
            await self._storage.complete_forum_backfill_request(
                req.id, state="failed", result="group_gone", completed_at=now
            )
            return
        try:
            pages = await self._backfill_thread(grp.platform_groupid)
        except httpx.HTTPError as exc:
            await self._storage.complete_forum_backfill_request(
                req.id, state="failed", result=f"http_error:{exc!r}", completed_at=now
            )
            return
        await self._storage.complete_forum_backfill_request(
            req.id, state="done", result=f"backfilled {pages} page(s)", completed_at=now
        )

    async def _backfill_thread(self, tid: str) -> int:
        """Fetch ALL pages of a thread (showthread.php?tid) and ingest them.

        Bypasses the shallow per-thread cap. put_message is insert-only, so the
        already-stored page-1 posts are skipped and the deep pages are added.
        """
        first = await self._get("showthread.php", params={"tid": tid})
        pages = thread_page_count(first.text)
        title = parse_thread_title(first.text)
        await self._ingest_page(tid, title, first.text)
        for page in range(2, pages + 1):
            resp = await self._get("showthread.php", params={"tid": tid, "page": page})
            await self._ingest_page(tid, title, resp.text)
        return pages

    async def _refetch_thread_unlocked(self, tid: str) -> None:
        """Re-fetch a thread after unlock and OVERWRITE its posts in place.

        Uses showthread.php?tid (MyBB canonical, no slug). The gated placeholders
        already exist, so we update by evidence_ref rather than insert.
        """
        try:
            first = await self._get("showthread.php", params={"tid": tid})
            pages = thread_page_count(first.text)
            for page in range(1, pages + 1):
                html = (
                    first.text
                    if page == 1
                    else (await self._get("showthread.php", params={"tid": tid, "page": page})).text
                )
                for post in parse_thread(html):
                    body = post.body_text
                    await self._storage.update_message_content(
                        f"forum:{self._board}:{tid}:{post.pid}",
                        body=body,
                        length_chars=len(body),
                        length_words=len(body.split()),
                        source_specific={
                            "body_html": post.body_html,
                            "edited": post.edited,
                            "reply_gated": post.reply_gated,
                            "author_display": post.author_display,
                            "author_username": post.author_username,
                        },
                    )
        except httpx.HTTPError as exc:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.refetch_failed",
                message=f"{self._identity_name}: re-fetch of {tid} after reply failed ({exc!r})",
            )

    async def _ingest_page(self, tid: str, title: str | None, html: str) -> None:
        posts = parse_thread(html)
        if not posts:
            _log.warning(
                "forum.empty_page",
                identity=self._identity_name,
                thread=tid,
            )
            return
        for post in posts:
            await self._ingest_post(tid, title, post)

    async def _ingest_post(self, tid: str, title: str | None, post: ParsedPost) -> None:
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
            title=title,
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
            source_specific={
                "body_html": post.body_html,
                "edited": post.edited,
                # [hide] gate: content locked until we reply. Recorded so the
                # operator can find gated threads and decide whether to unlock.
                "reply_gated": post.reply_gated,
                # Denormalized author so the thread reader renders posts without
                # an actor join per row.
                "author_display": post.author_display,
                "author_username": post.author_username,
            },
        )
        written = await self._storage.put_message(msg_row, [])

        # Only publish NEW posts: put_message is idempotent, so a re-poll of an
        # unchanged thread writes nothing and must not re-spam the sensor.
        if not written:
            return

        # Pure-quote posts strip to an empty body: no authored words to classify
        # (the quoted content belongs to someone else). Store as evidence but do
        # NOT feed the classifier — same gate as a telegram forward. Otherwise the
        # incident feed fills with bodyless "row not retained" noise.
        if not body.strip():
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
