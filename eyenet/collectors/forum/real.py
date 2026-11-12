# SPDX-License-Identifier: AGPL-3.0-or-later
"""`ForumCollector` - live forum collector over an imported cookie jar.

Engine-agnostic (MyBB, XenForo, ...): the per-engine parser is resolved from the
identity's ``forum_engine`` via ``get_parser`` in ``on_subscribe``. Exported also
as ``MyBBForumCollector`` for back-compat.

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
import contextlib
import faulthandler
import hashlib
import json
import os
import random
import signal
import time
import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy.exc import OperationalError

from eyenet.collectors.base._credentials import materialize_forum_session
from eyenet.collectors.base.skeleton import CollectorSkeleton, VisibleGroup
from eyenet.collectors.forum import (
    ForumParser,
    ParsedPost,
    get_parser,
    parse_reply_form,
    posted_at_to_utc,
)
from eyenet.collectors.forum._flaresolverr import FlareSolverrClient
from eyenet.collectors.forum._timing_presets import (
    DEFAULT_DELAY_MAX,
    DEFAULT_DELAY_MIN,
    DEFAULT_DISCOVERY_DEPTH,
    DEFAULT_RETRY_AFTER,
    FORUM_TLS_IMPERSONATE_TARGETS,
    RETRY_AFTER_PAD,
)
from eyenet.contracts._base import TraceContext
from eyenet.contracts.actor import actor_key
from eyenet.contracts.bus import Bus
from eyenet.contracts.collector import CollectorHealth
from eyenet.contracts.enums import (
    CollectorObservedState,
    CollectorState,
    GroupKind,
    SourceKind,
    SystemLogLevel,
)
from eyenet.contracts.identity_pool import IdentityPool
from eyenet.contracts.raw_message import RawMessageEnvelope, subject_for
from eyenet.contracts.supervisor import ScanVisibleGroupsCommand, command_subject_for
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.search_indexer.events import publish_entity_changed
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.logging import get_logger
from eyenet.telemetry.propagation import current_traceparent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptography.fernet import Fernet

    from eyenet.identity_pool.loader import IdentityFileEntry

_log = get_logger()

# Pacing + 429-backoff timing live in _timing_presets (the examinable profiles).
# One paced discovery sweep, then rest. Re-enumerating 500-page categories every
# minute would be its own DoS; a category rarely gains threads that fast.
_DEFAULT_DISCOVERY_INTERVAL = 21_600  # 6h
# 0 = walk every page of a category (full backfill). Listings are fetched sorted
# by thread CREATION date desc (see ForumParser.category_url by_created), so a
# positive cap gets the most recently CREATED threads first.
_DEFAULT_MAX_CATEGORY_PAGES = 0
# Per-thread depth on a sweep. Page 1 is the leak + the OP (the signal + the
# actor worth scraping); deeper pages are leecher "thanks" that bloat the corpus.
# So default shallow for breadth; the operator backfills a specific thread deeper
# on demand (POST .../backfill). 0 = all pages.
_DEFAULT_MAX_THREAD_PAGES = 1
# Steady-state breadth: once a category's archive is backfilled, re-sweep the top
# N creation-sorted pages each pass (not just page 1). Page 1 alone misses a fresh
# leak that spam already pushed to page 2-3 between sweeps; the creation-date sort
# makes the top N a deterministic newest-first window. 0 = page 1 only.
_DEFAULT_STEADY_PAGES = 3
# Hard per-request deadline (backstop ABOVE the httpx/curl 30s). Over SOCKS/Tor the
# client's own timeout has proven unreliable — a slow onion wedged a whole sweep for
# hours with no timeout firing, freezing the backfill cursor. asyncio.wait_for bounds
# EVERY board request no matter what the transport does, so a hang raises promptly,
# the existing HTTPError handlers log it + persist the cursor, and the sweep resumes.
_REQUEST_HARD_TIMEOUT = 45.0
# Sweep watchdog: INACTIVITY-based, not wall-clock. A single sweep legitimately runs
# for 20-30min+ at lurker pace (20-60s/req over 23 threads, plus FlareSolverr solve
# time), so total duration says NOTHING about health — an earlier wall-clock cap
# guillotined healthy-but-slow sweeps. What a real wedge looks like is NO request
# completing for a long stretch. Each request is already hard-capped at
# _REQUEST_HARD_TIMEOUT (45s) and the jitter sleep caps at 60s, so a live sweep marks
# activity at least every ~105s; this threshold sits well above that. Cross it and the
# sweep is genuinely stuck OFF-request (an unbounded await) — dump the async stack at
# ERROR (bypasses the 10% non-error sampling), cancel, and if it won't die, exit for a
# clean supervisor respawn.
_SWEEP_INACTIVITY_S = 300.0
# How often the watchdog wakes to check the inactivity clock.
_SWEEP_WATCHDOG_POLL_S = 30.0
# After cancelling a wedged sweep, how long to let it unwind before concluding the
# await is uncancellable and exiting the process for a respawn.
_SWEEP_CANCEL_GRACE_S = 15.0
# pf-auto's per-account thread throttle answers with HTTP 200 and a ~160-byte
# "Slow down now" stub instead of a 429 (measured on pwnforums onion + clearnet). A
# real forum page is tens of KB, so a sub-2KB body carrying that marker is the throttle,
# never genuine content. Treated as a rate-limit so the collector backs off instead of
# marching the cursor over empty pages. Re-measure if the stub changes.
_THROTTLE_BODY_MAX = 2048
_THROTTLE_MARKERS = ("slow down now", "slow down")
# Subforum-discovery depth default (DEFAULT_DISCOVERY_DEPTH) lives in
# _timing_presets alongside the per-level overrides.

# Impersonate the browser that logs in over Tor and mints the cookie jar (Tor
# Browser = Firefox ESR). Matching its header profile keeps the collector's
# requests CONSISTENT with the session those cookies were minted under — a
# UA/Accept flip mid-session is itself a ban signal. The UA is per-identity
# (forum_user_agent) so it tracks the operator's actual Tor Browser build; the
# rest are TB-uniform. Sec-Fetch-Site is per-request (set in _get: "none" for a
# fresh navigation, "same-origin" once a Referer chains it).
_DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
# FlareSolverr sidecar endpoint for the WAF-bypass path (forum_enable_waf_bypass).
# The compose service name resolves inside the docker network; override for a
# differently-placed sidecar.
_FLARESOLVERR_URL = os.environ.get("EYENET_FLARESOLVERR_URL", "http://flaresolverr:8191")
_BASE_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Sec-GPC": "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Priority": "u=0, i",
    # Accept-Encoding is deliberately NOT set: httpx advertises exactly the
    # codecs it can decode (gzip, deflate, br, zstd — with the brotli + zstandard
    # extras in pyproject), which matches Tor Browser. Advertising a codec we
    # can't inflate would hand us undecodable bodies. curl-cffi (the impersonation
    # path) sets its own Accept-Encoding too, so leaving it unset is correct for
    # BOTH clients — do not add it here.
}


def _validate_impersonate(target: str) -> None:
    """Fail closed on an unknown impersonation target (never fall back to httpx's
    OpenSSL fingerprint — that would defeat the whole point and get us banned). The
    allowed set + the FF-version coupling live in _timing_presets +
    FORUM_TLS_IMPERSONATE_TARGETS; see CLAUDE.md 'load-bearing TLS/evasion defaults'."""
    if target not in FORUM_TLS_IMPERSONATE_TARGETS:
        raise RuntimeError(
            f"forum_tls_impersonate={target!r} is not an allowed Firefox target "
            f"{sorted(FORUM_TLS_IMPERSONATE_TARGETS)}; it must track the cookie-mint browser "
            "(see CLAUDE.md 'load-bearing TLS/evasion defaults')"
        )


class RateLimited(Exception):  # noqa: N818 - a control signal, not an error condition
    """A board 429'd us (or we're still inside its cooldown). Caught at the tick
    boundary to abort the sweep SILENTLY — never retried, never polled."""


class UnparseableDateError(Exception):
    """A post date could not be parsed to a real timestamp.

    FAIL-CLOSED: we refuse to ingest the post rather than substitute now() (which
    silently manufactures false recency on an old leak — the single most damaging
    field to get wrong, see CLAUDE.md 4a). Caught at the tick boundary, where it
    FAULTS the whole collector: the parser is missing a board's date format and a
    human must add it, not let the collector backfill garbage. Carries the raw
    string so the operator can extend the parser from the log line.
    """

    def __init__(self, *, tid: str, pid: str, raw: str) -> None:
        self.tid = tid
        self.pid = pid
        self.raw = raw
        detail = f"unparseable date {raw!r}" if raw.strip() else "date span missing"
        super().__init__(f"tid={tid} pid={pid}: {detail}")


def _zero_traceparent() -> str:
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


def _is_throttle_body(resp: Any) -> bool:
    """True if ``resp`` is pf-auto's 200 "Slow down now" throttle stub, not real content.

    Measured: a ~160-byte page whose body is just ``<pre>Slow down now</pre>``. Gated on
    a small body so a genuine thread that merely contains the phrase in a post can't
    false-trip (real pages are tens of KB). See ``_THROTTLE_BODY_MAX``.
    """
    body = resp.text or ""
    if len(body) > _THROTTLE_BODY_MAX:
        return False
    low = body.lower()
    return any(m in low for m in _THROTTLE_MARKERS)


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


def _category_slug(url: str) -> str:
    """Storable category slug = the link's path relative to the board root.

    Keeps the WHOLE path (minus leading/trailing slashes), not just the last
    segment: MyBB forums are flat (``Forum-Databases``) so this is unchanged, but
    XenForo routes are multi-segment (``/forums/db-leaks/`` -> ``forums/db-leaks``,
    or a custom route ``/foros/x/`` -> ``foros/x``). category_url rebuilds the
    fetch URL from this slug, so dropping ``forums/`` sends every sweep to a
    soft-404. The route prefix must survive.
    """
    return urlparse(url).path.strip("/")


# Section prefixes DarkForums prepends to a thread slug per forum; dropped when a
# thread is MOVED (e.g. to Removed Content), which re-slugs it. Normalizing them
# away lets a moved tid-less thread dedupe to its captured copy. This is the
# FALLBACK path only (used when a thread page yields no canonical tid, which is
# rare); the primary dedup key is the page's tid via the alias table.
# ponytail: a short known-prefix list, extend as new sections surface. Anchored to
# the ``Thread-`` head so an in-title "DATABASE-" mid-slug is never touched.
_SECTION_SLUG_PREFIXES = ("DATABASE-", "STEALER-LOGS-", "STEALER-")


def _normalize_thread_slug(key: str) -> str:
    """Strip a leading section prefix from a ``Thread-<section>-<title>`` slug.

    No-op for a numeric tid key or a slug without a known section prefix.
    """
    if not key.startswith("Thread-"):
        return key
    rest = key[len("Thread-") :]
    for prefix in _SECTION_SLUG_PREFIXES:
        if rest.startswith(prefix):
            return "Thread-" + rest[len(prefix) :]
    return key


class ForumCollector(CollectorSkeleton):
    """Cookie-session forum collector: fetch -> parse -> store -> publish.

    Engine-agnostic: the parser (MyBB, XenForo, ...) is resolved from the
    identity's ``forum_engine`` via :func:`get_parser` in :meth:`on_subscribe`,
    so URL/sort syntax and DOM selectors stay in the parser module. The write
    path (reply-to-unlock, single-thread deep backfill) is still MyBB-only."""

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
        # Any, not httpx.AsyncClient: on the clearnet-WAF path this holds a
        # curl-cffi AsyncSession instead (duck-compatible: .get/.post ->
        # .status_code/.headers/.text). Tests still inject an httpx client.
        self._client: Any = http_client
        self._owns_client = http_client is None
        self._source_uuid: UUID | None = None
        self._collector_id: UUID | None = None
        self._board = ""
        self._base_url = ""  # absolute origin, for building realistic Referers
        self._thread_urls: list[str] = []
        # Pacing / discovery (overridden from the identity in on_subscribe).
        self._delay_min = DEFAULT_DELAY_MIN
        self._delay_max = DEFAULT_DELAY_MAX
        self._discovery_interval = float(_DEFAULT_DISCOVERY_INTERVAL)
        self._max_category_pages = _DEFAULT_MAX_CATEGORY_PAGES
        self._max_thread_pages = _DEFAULT_MAX_THREAD_PAGES
        self._steady_pages = _DEFAULT_STEADY_PAGES
        self._discovery_depth = DEFAULT_DISCOVERY_DEPTH
        # Parser resolved from forum_engine in on_subscribe; default MyBB so
        # methods are usable before subscribe (tests, standalone probes).
        self._parser: ForumParser = get_parser("mybb")
        # Monotonic deadline: while now < this, every request is refused BEFORE it
        # hits the wire (poking during a 429 cooldown re-arms the server's timer).
        self._cooldown_until = 0.0
        # Monotonic timestamp of the last completed request, for the inactivity-based
        # sweep watchdog. Bumped in _get/_post; a live sweep keeps it fresh.
        self._last_request_at = 0.0
        # Fail-closed halt reason. Set when the collector hits data it refuses to
        # ingest (an unparseable post date). While set, tick() is a no-op: the
        # collector stays alive but makes ZERO board requests and writes NOTHING,
        # until an operator restarts it (clears this in-process flag). health()
        # reports CollectorState.FAULTED so the fault is visible on the API.
        self._faulted: str | None = None
        # When we last swept (monotonic) + the monitored set that sweep was for
        # (so a newly-monitored category triggers a re-sweep next tick instead of
        # waiting out the interval).
        self._last_discovery = 0.0
        self._last_monitored: frozenset[str] = frozenset()

    async def on_subscribe(self) -> None:
        await super().on_subscribe()
        # `kill -USR1 <pid>` dumps every thread's Python stack to stderr (container
        # logs) — a live, zero-dependency probe for a wedged collector when the
        # minimal image has no py-spy. Harmless if SIGUSR1 is unavailable.
        with contextlib.suppress(ValueError, OSError, RuntimeError):
            faulthandler.register(signal.SIGUSR1, all_threads=True)
        entry = cast("IdentityFileEntry", self._claimed)
        self._board = urlparse(entry.forum_base_url or "").netloc or (entry.forum_base_url or "")
        self._base_url = (entry.forum_base_url or "").rstrip("/")
        self._thread_urls = list(entry.forum_thread_urls)
        # Pacing comes pre-resolved on the entry (an evasion level, if the operator
        # picked one, is expanded to forum_delay_min/max at provision time — see
        # _timing_presets.resolve_evasion_profile). The collector just honours it.
        self._delay_min = float(getattr(entry, "forum_delay_min", DEFAULT_DELAY_MIN))
        self._delay_max = float(getattr(entry, "forum_delay_max", DEFAULT_DELAY_MAX))
        self._discovery_interval = float(
            getattr(entry, "forum_discovery_interval", _DEFAULT_DISCOVERY_INTERVAL)
        )
        self._max_category_pages = int(
            getattr(entry, "forum_max_category_pages", _DEFAULT_MAX_CATEGORY_PAGES)
        )
        self._max_thread_pages = int(
            getattr(entry, "forum_max_thread_pages", _DEFAULT_MAX_THREAD_PAGES)
        )
        self._steady_pages = int(getattr(entry, "forum_steady_pages", _DEFAULT_STEADY_PAGES))
        self._discovery_depth = int(
            getattr(entry, "forum_discovery_depth", DEFAULT_DISCOVERY_DEPTH)
        )
        # Pick the engine parser (MyBB default). An unknown engine raises here —
        # fail loud at boot, same posture as forum_tls_impersonate; the API
        # validates against the registry so a live value is always known.
        self._parser = get_parser(getattr(entry, "forum_engine", "mybb"))

        if self._client is None:
            self._client = await self._build_forum_client(entry)

        # Our own collector row: the operator's monitored-category memberships are
        # keyed to it (list_active_memberships). Without it the monitor set stays
        # empty and we crawl nothing (fail-closed).
        collector = await self._storage.resolve_collector_by_instance_id(self.instance_id)
        self._collector_id = collector.id if collector is not None else None
        # Ingest into the source the OPERATOR CHOSE when creating this collector
        # (collector.source_id). Do NOT auto-create a forum:<identity-name> source
        # and rebind to it — that spawned a SECOND, divergent source: the operator's
        # monitored categories (+ the reader) landed on their picked source while
        # the crawl stored threads into the auto-created one, so the reader showed
        # an empty category. Fall back to a per-identity source only when there is
        # no collector row (standalone / tests).
        if collector is not None:
            self._source_uuid = collector.source_id
        else:
            # Standalone / tests path: no collector row, so fall back to the
            # identity's source_id. Do NOT upsert a `forum:{entry.name}`
            # source here, which would silently create a parallel source if
            # the operator bound this identity to a non-conventionally-named
            # source (same bug the comment above describes, in a different
            # flavour).
            identity_row = await self._storage.get_identity_by_name(entry.name)
            if identity_row is None:
                raise RuntimeError(
                    f"identity {entry.name!r} was claimed from the pool but has "
                    "no DB row; identity pool and storage are out of sync"
                )
            self._source_uuid = identity_row.source_id

        # Listen for an operator-triggered rediscovery (POST /v1/collectors/{id}/
        # rediscover or /v1/groups/scan). This is the ONLY way discovery re-runs
        # after the one-time startup scan — an explicit refresh, never automatic.
        # Subscribed BEFORE the discovery gate's early-return so an already-mapped
        # collector still responds to the command.
        async def _on_command(_subject: str, payload: bytes, _headers: dict[str, str]) -> None:
            try:
                if json.loads(payload).get("kind") == "scan_visible_groups":
                    ScanVisibleGroupsCommand.model_validate_json(payload)
                    if self._source_uuid is not None:
                        await self.scan_visible_groups(source_id=self._source_uuid)
            except (RateLimited, OperationalError, httpx.HTTPError) as exc:
                await self.syslog(
                    level=SystemLogLevel.WARN,
                    event="forum.rediscover_incomplete",
                    message=f"{self._identity_name}: rediscover hit {type(exc).__name__} ({exc})",
                )
            except Exception as exc:
                _log.error("forum.command_error", identity=self._identity_name, error=str(exc))

        await self.bus.subscribe(command_subject_for(self.instance_id), _on_command)

        # Populate /monitored-groups with the board's categories so the operator
        # can pick which to monitor. Read-only page fetch, nothing joined.
        #
        # Discovery runs ONCE per source — NOT on every (re)subscribe. A restart or
        # redeploy must never re-enumerate a board we've already mapped: it's
        # wasteful, it's loud, and on a rate-limited board (pwnforums) it re-trips
        # the 429. So skip the startup scan when the source already has candidates;
        # the operator forces a refresh explicitly via POST /v1/groups/scan (which
        # calls scan_visible_groups directly, bypassing this gate).
        already = await self._storage.count_candidates(source_id=self._source_uuid)
        if already:
            _log.info(
                "forum.discovery_skipped_already_mapped",
                identity=self._identity_name,
                source_id=str(self._source_uuid),
                candidates=already,
            )
            return
        # First-ever discovery for this source. BEST-EFFORT: it must NEVER crash the
        # collector (a failure here used to propagate out of on_subscribe and kill
        # the process, so the supervisor respawned it in a tight loop). The core job
        # (crawling monitored categories in tick()) does not need discovery to have
        # succeeded. Catch the transient vectors — a 429 (RateLimited), a DB lock
        # from a sibling collector's bulk ingest (OperationalError), a Tor/network
        # hiccup (httpx) — log the cause, and start anyway.
        try:
            if await self._check_session():
                await self.scan_visible_groups(source_id=self._source_uuid)
        except (RateLimited, OperationalError, httpx.HTTPError) as exc:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.discovery_failed_at_startup",
                message=(
                    f"{self._identity_name}: startup discovery failed "
                    f"({type(exc).__name__}: {exc}) - collector starting anyway"
                ),
            )

    async def _build_forum_client(self, entry: IdentityFileEntry) -> Any:
        """Per-identity HTTP client. curl-cffi (real-Firefox TLS via
        ``forum_tls_impersonate``) for a CLEARNET https board behind a JA3/JA4 WAF;
        httpx for the onion/Tor + default path (``proxy_uri`` = socks5h://tor:9050
        routes the crawl via Tor, which wraps the TLS so impersonation is moot).
        See CLAUDE.md "4a. load-bearing TLS/evasion defaults"."""
        cookies = materialize_forum_session(entry, self._session_key)
        proxy = getattr(entry, "proxy_uri", None) or None
        # WAF-bypass path: a clearnet board stacking a Cloudflare JS/behavioural
        # challenge + Anubis PoW can only be cleared by a real browser. Route every
        # request through the FlareSolverr sidecar, which drives that browser and
        # returns solved HTML. Our warmed jar is injected so the browser is logged
        # in. Plain on/off per identity - independent of pacing/evasion (a WAF
        # challenge implies nothing about rate limits). See _flaresolverr.py.
        if getattr(entry, "forum_enable_waf_bypass", False):
            await self.syslog(
                level=SystemLogLevel.NOTICE,
                event="forum.waf_bypass_enabled",
                message=f"{self._identity_name}: routing via FlareSolverr {_FLARESOLVERR_URL}",
            )
            return FlareSolverrClient(
                endpoint=_FLARESOLVERR_URL,
                base_url=entry.forum_base_url or "",
                cookies=cookies,
                proxy_uri=proxy,
            )
        user_agent = getattr(entry, "forum_user_agent", None) or _DEFAULT_USER_AGENT
        headers = {**_BASE_HEADERS, "User-Agent": user_agent}
        impersonate = getattr(entry, "forum_tls_impersonate", None)
        base_url = entry.forum_base_url or ""
        if impersonate and proxy:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.tls_impersonate_ignored_on_proxy",
                message=f"{self._identity_name}: forum_tls_impersonate={impersonate} "
                "ignored - Tor/proxy path uses httpx",
            )
        if impersonate and not proxy and base_url.startswith("https"):
            _validate_impersonate(impersonate)
            # lazy import: only the clearnet-WAF path needs curl-cffi
            from curl_cffi.requests import AsyncSession  # noqa: PLC0415

            return AsyncSession(
                base_url=base_url,
                cookies={c.name: c.value for c in cookies.jar if c.value is not None},
                headers=headers,
                impersonate=impersonate,
                timeout=30.0,
                allow_redirects=True,
            )
        return httpx.AsyncClient(
            base_url=base_url,
            cookies=cookies,
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
            proxy=proxy,
        )

    async def stop(self) -> None:
        if self._owns_client and self._client is not None:
            # httpx uses aclose(); curl-cffi's AsyncSession uses close(). Both async.
            closer = getattr(self._client, "aclose", None) or self._client.close
            await closer()
        await super().stop()

    async def health(self) -> CollectorHealth:
        """Report FAULTED while halted on unparseable data; else delegate."""
        base = await super().health()
        if self._faulted is not None:
            return base.model_copy(
                update={"state": CollectorState.FAULTED, "last_error": self._faulted}
            )
        return base

    def _abs(self, path: str) -> str:
        """Absolute origin URL for a board-relative ``path`` (for Referer)."""
        if not self._base_url:
            return path
        return f"{self._base_url}/{path.lstrip('/')}"

    @staticmethod
    def _nav_headers(referer: str | None) -> dict[str, str]:
        """Per-request navigation headers that complete the browser profile.

        A fresh navigation (no Referer) sends ``Sec-Fetch-Site: none``; once a
        Referer chains the request within the same origin it becomes
        ``same-origin`` — mirroring a human clicking index -> category -> thread
        rather than a crawler hitting deep URLs cold.
        """
        if referer:
            return {"Referer": referer, "Sec-Fetch-Site": "same-origin"}
        return {"Sec-Fetch-Site": "none"}

    def _guard_cooldown(self) -> None:
        """Refuse a request while inside a 429 cooldown — BEFORE it hits the wire.

        Poking a rate-limited board (even one request, even a refresh) re-arms its
        timer, so a naive backoff that keeps probing never recovers. We stay fully
        silent until the deadline, then the next request goes through normally."""
        remaining = self._cooldown_until - time.monotonic()
        if remaining > 0:
            raise RateLimited(f"in cooldown, ~{remaining:.0f}s of silence left")

    def _note_rate_limit(self, resp: httpx.Response) -> None:
        """Arm the silent cooldown + abort the sweep on a rate-limit. We wait the
        Retry-After PADDED with jitter (never the exact second — a robotic tell).

        Covers two shapes: a real 429 (with Retry-After), and pf-auto's SNEAKY
        per-account throttle that returns HTTP 200 with a tiny "Slow down now" body
        (measured on pwnforums, both onion and clearnet). Without the second check the
        collector reads the throttle stub as an empty thread and marches the cursor over
        un-ingested pages — poisoning the backfill. A 200 throttle carries no
        Retry-After, so it uses the measured default backoff.
        """
        is_429 = resp.status_code == httpx.codes.TOO_MANY_REQUESTS
        throttled_200 = not is_429 and _is_throttle_body(resp)
        if not (is_429 or throttled_200):
            return
        ra = resp.headers.get("retry-after", "") if is_429 else ""
        # ponytail: integer-seconds only (what real boards send); an HTTP-date
        # Retry-After falls back to the measured default — add dateparse if ever seen.
        base = float(ra) if ra.isdigit() else DEFAULT_RETRY_AFTER
        pad = random.uniform(*RETRY_AFTER_PAD)  # noqa: S311 - jitter, not crypto
        self._cooldown_until = time.monotonic() + base + pad
        shape = "429" if is_429 else "200 'Slow down now' throttle"
        raise RateLimited(
            f"{shape} -> silent for ~{base + pad:.0f}s (Retry-After={ra or 'absent'})"
        )

    # -> Any: the response is an httpx.Response OR a curl-cffi Response (impersonation
    # path); both expose .status_code/.headers/.text, which is all callers touch.
    async def _get(self, url: str, *, referer: str | None = None, **kw: Any) -> Any:
        """Every board request funnels through here: sequential + jittered delay.

        This is the single choke point that keeps the collector browsing-speed.
        There is deliberately no un-throttled request path. ``referer`` threads a
        realistic navigation chain (see :meth:`_nav_headers`). A 429 (or being mid
        cooldown) raises :class:`RateLimited` — caught at the tick boundary.
        """
        if self._client is None:  # pragma: no cover - guarded by callers
            raise RuntimeError("forum collector http client not initialized")
        self._guard_cooldown()
        headers = {**kw.pop("headers", {}), **self._nav_headers(referer)}
        await asyncio.sleep(random.uniform(self._delay_min, self._delay_max))  # noqa: S311 - jitter, not crypto
        resp = await self._request(self._client.get(url, headers=headers, **kw), url)
        self._last_request_at = time.monotonic()  # progress signal for the sweep watchdog
        self._note_rate_limit(resp)
        return resp

    async def _post(
        self, url: str, *, referer: str | None = None, **kw: Any
    ) -> Any:  # -> Any: see _get
        """Throttled POST — the ONLY write path, same jittered pacing as reads."""
        if self._client is None:  # pragma: no cover - guarded by callers
            raise RuntimeError("forum collector http client not initialized")
        self._guard_cooldown()
        headers = {**kw.pop("headers", {}), **self._nav_headers(referer)}
        await asyncio.sleep(random.uniform(self._delay_min, self._delay_max))  # noqa: S311 - jitter, not crypto
        resp = await self._request(self._client.post(url, headers=headers, **kw), url)
        self._last_request_at = time.monotonic()  # progress signal for the sweep watchdog
        self._note_rate_limit(resp)
        return resp

    @staticmethod
    async def _request(coro: Any, url: str) -> Any:
        """Await a board request under a HARD deadline. The transport's own timeout has
        proven unreliable over SOCKS/Tor (a hung onion froze a sweep for hours), so this
        backstops EVERY request; a timeout surfaces as httpx.ReadTimeout, which the
        callers already handle (log + persist cursor + resume) instead of wedging."""
        try:
            return await asyncio.wait_for(coro, timeout=_REQUEST_HARD_TIMEOUT)
        except (TimeoutError, asyncio.TimeoutError) as exc:  # noqa: UP041 - explicit for <3.11 alias
            raise httpx.ReadTimeout(f"hard {_REQUEST_HARD_TIMEOUT:.0f}s deadline on {url}") from exc

    @staticmethod
    def _visible_group(slug: str) -> VisibleGroup:
        return VisibleGroup(
            platform_groupid=slug,
            kind=GroupKind.FORUM_CATEGORY,
            title=slug.replace("Forum-", "").replace("-", " "),
            is_member=True,
        )

    async def _iter_visible_groups(self) -> AsyncIterator[VisibleGroup]:
        """Stream the board's forums (GroupKind.FORUM_CATEGORY), INDEX FIRST.

        The index is a SINGLE request that already lists every top-level category,
        so we yield all of those up front — before descending for subforums — and
        the caller (:meth:`scan_visible_groups`) persists each as it is yielded.
        That is the whole point: top-level visibility appears after one request,
        not after the entire depth-N walk completes. Then we descend into each
        forum's child SUBFORUMS up to ``forum_discovery_depth`` levels, streaming
        each as found. Every fetch goes through ``_get`` so the walk is paced by
        the identity's evasion preset (and the 429 gate). DISCOVERY only: nothing
        here joins anything; the crawl loop stays flat + fail-closed.
        """
        index = await self._get("/")
        seen: set[str] = set()
        frontier: list[tuple[str, int]] = []
        # Top-level categories from the single index request — yield them ALL now.
        for url in self._parser.parse_forum_links(index.text):
            slug = _category_slug(url)
            if slug not in seen:
                seen.add(slug)
                yield self._visible_group(slug)
                frontier.append((slug, 0))
        await self.syslog(
            level=SystemLogLevel.NOTICE,
            event="forum.discovery_index_listed",
            message=f"{self._identity_name}: index listed {len(frontier)} top-level categories",
        )
        # Descend for subforums (paced), streaming each as found. A cycle guard
        # (seen) stops a subforum that links back up from looping.
        while frontier:
            slug, depth = frontier.pop(0)
            if depth >= self._discovery_depth:
                continue
            try:
                page = await self._get(slug, referer=self._base_url or None)
            except httpx.HTTPError as exc:
                # One forum failing to enumerate must not abort the whole tree
                # walk (a blocked/removed forum just contributes no children).
                await self.syslog(
                    level=SystemLogLevel.WARN,
                    event="forum.subforum_enumerate_failed",
                    message=f"{self._identity_name}: {slug} subforum scan failed ({exc!r})",
                )
                continue
            new = 0
            for child_url in self._parser.parse_subforum_links(page.text):
                child = _category_slug(child_url)
                if child not in seen:
                    seen.add(child)
                    yield self._visible_group(child)
                    frontier.append((child, depth + 1))
                    new += 1
            if new:
                _log.info(
                    "forum.discovery_subforum_listed",
                    identity=self._identity_name,
                    instance_id=self._instance_id,
                    parent=slug,
                    new_subforums=new,
                    depth=depth + 1,
                )

    async def enumerate_visible_groups(self) -> list[VisibleGroup]:
        """Full list of visible categories (collects the incremental stream).

        Kept for callers that want the whole set at once; live discovery uses
        :meth:`scan_visible_groups`, which persists each category as it streams.
        """
        return [g async for g in self._iter_visible_groups()]

    async def scan_visible_groups(self, *, source_id: UUID) -> int:
        """Incremental discovery: persist each category the MOMENT it is discovered.

        Overrides the generic (collect-then-persist) scan so the index's top-level
        categories land in the candidate set after the single index request, not
        after the whole depth-N walk — which over Tor at a slow evasion preset can
        be the better part of an hour. Emits NOTICE events so the walk is traceable
        in the system log.
        """
        await self.syslog(
            level=SystemLogLevel.NOTICE,
            event="forum.discovery_started",
            message=f"{self._identity_name}: discovery (depth={self._discovery_depth})",
        )
        n = 0
        async for g in self._iter_visible_groups():
            await self._storage.ensure_candidate(
                source_id=source_id,
                platform_groupid=g.platform_groupid,
                seen_at=datetime.now(tz=UTC),
                kind=g.kind,
                title=g.title,
                member_dialog=g.is_member,
            )
            n += 1
            if n % 25 == 0:
                _log.info(
                    "forum.discovery_progress",
                    identity=self._identity_name,
                    instance_id=self._instance_id,
                    persisted=n,
                )
        await self.syslog(
            level=SystemLogLevel.NOTICE,
            event="forum.discovery_complete",
            message=f"{self._identity_name}: {n} categories persisted",
        )
        _log.info(
            "collector.visible_groups_scanned",
            identity=self._identity_name,
            instance_id=self._instance_id,
            count=n,
        )
        return n

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
        logged_in = self._parser.is_logged_in(resp.text)
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
        # FAULTED: a fail-closed halt (unparseable date). Stay fully idle — no board
        # requests, no writes — until an operator restarts the collector. We do NOT
        # keep retrying: retrying would re-hit the same bad data and either loop or
        # resume poisoning the corpus, which is exactly what the halt prevents.
        if self._faulted is not None:
            return
        # In a 429 cooldown: stay fully silent — don't even enter the sweep. Without
        # this, every tick re-entered _tick_body (the throttle handler below resets
        # _last_discovery=0), logged a sweep_start, then aborted at the _get cooldown
        # guard — a per-second busy-spin that spammed the DB with forum.rate_limited
        # rows for the whole ~10min window. Returning here makes a throttled collector
        # truly idle; _last_discovery==0 still re-sweeps on the first tick AFTER the
        # cooldown lapses.
        if time.monotonic() < self._cooldown_until:
            return
        try:
            await self._tick_body()
        except RateLimited as exc:
            # The board 429'd us. Abort this sweep SILENTLY — no retry, no poll.
            # Reset _last_discovery so the first tick after the cooldown lapses
            # re-sweeps promptly; the guard above keeps us idle until then.
            self._last_discovery = 0.0
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.rate_limited",
                message=f"{self._identity_name}: {exc}",
            )
        except UnparseableDateError as exc:
            # Fail-closed: a post date we can't parse would be now()-substituted
            # (false recency). We did NOT write it. HALT the collector rather than
            # keep backfilling garbage — the parser is missing this board's date
            # format and a human must add it (the raw string is in the message).
            self._faulted = str(exc)
            await self.syslog(
                level=SystemLogLevel.ERROR,
                event="forum.faulted_unparseable_date",
                message=(
                    f"{self._identity_name}: FAULTED - refusing to ingest a post with an "
                    f"unparseable date ({exc}); collector HALTED (no now() backfill). "
                    "Add the board's date format to _mybb._parse_date and restart."
                ),
            )
            # Surface the fault on the fleet view: write observed_state=FAULTED +
            # the reason to our own collector row. The supervisor preserves it
            # (liveness won't re-stamp RUNNING), so the operator sees FAULTED on
            # the list instead of a misleading "running".
            if self._collector_id is not None:
                await self._storage.record_collector_observed_state(
                    collector_id=self._collector_id,
                    observed_state=CollectorObservedState.FAULTED,
                    last_error_type="unparseable_date",
                    last_error_message=self._faulted,
                )

    async def _tick_body(self) -> None:
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
        # as we discover them (creation-sorted newest-first) so posts flow from
        # the first minute instead of after a full multi-hour enumeration.
        for slug in sorted(monitored):
            try:
                await self._crawl_category_watched(slug)
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

    async def _process_category_page(self, slug: str, html: str) -> int:
        """Poll every thread linked on one category page. Returns count polled.

        Read-only; each thread is polled immediately (interleaved). A per-thread
        DB lock is skipped, not fatal: the category still finishes and the next
        sweep re-polls (newest-first, so a skip is re-picked-up promptly).
        """
        threads = 0
        category_ref = self._abs(slug)  # Referer for each thread: its category page
        for thread_url in self._parser.parse_thread_links(html):
            try:
                # Poll first: it resolves the thread's STABLE key (canonical tid
                # via the alias) from the page, so the category->thread link is
                # recorded under the same key the thread ingests under, not the
                # (re-sluggable) listing URL.
                key = await self._poll_thread(thread_url, referer=category_ref)
                if key is not None and self._source_uuid is not None:
                    await self._storage.record_forum_thread_link(
                        source_id=self._source_uuid,
                        category_platform_groupid=slug,
                        thread_platform_groupid=key,
                        seen_at=datetime.now(tz=UTC),
                    )
                threads += 1
            except OperationalError as exc:
                await self.syslog(
                    level=SystemLogLevel.WARN,
                    event="forum.thread_crawl_locked",
                    message=f"{self._identity_name}: {thread_url} DB-locked, skipped ({exc!r})",
                )
        return threads

    async def _crawl_category_watched(self, slug: str) -> None:
        """Run one category sweep under an INACTIVITY watchdog.

        A sweep legitimately runs for 20-30min+ at lurker pace, so total duration
        is NOT a health signal (a wall-clock cap guillotines healthy-but-slow work).
        Instead we watch for *no request completing* for ``_SWEEP_INACTIVITY_S``:
        every request is hard-capped at ``_REQUEST_HARD_TIMEOUT`` and bumps
        ``_last_request_at``, so a live sweep stays fresh and only a genuine
        off-request wedge (an unbounded await) crosses the line. When it does, dump
        the async stack at ERROR (bypasses the 10% non-error sampling), cancel, and
        if the await is uncancellable, exit the process for a clean supervisor
        respawn rather than zombie forever.
        """
        task = asyncio.create_task(self._crawl_category(slug))
        self._last_request_at = time.monotonic()  # arm the clock at sweep start
        while True:
            done, _pending = await asyncio.wait({task}, timeout=_SWEEP_WATCHDOG_POLL_S)
            if task in done:
                await task  # propagate result / re-raise (OperationalError, RateLimited)
                return
            if time.monotonic() - self._last_request_at >= _SWEEP_INACTIVITY_S:
                break  # no request has completed in too long -> genuinely wedged
        idle = time.monotonic() - self._last_request_at
        # get_stack() returns the full await chain (oldest->newest). Render each frame
        # on its own (limit=1) so we see the DEEPEST await, not just the outer call
        # site - the earlier frames[-1]+format_stack only showed the outermost frame.
        frames = task.get_stack()
        where = (
            "".join("".join(traceback.format_stack(f, limit=1)) for f in frames)
            if frames
            else "<no stack captured>"
        )
        await self.syslog(
            level=SystemLogLevel.ERROR,
            event="forum.sweep_watchdog",
            message=(
                f"{self._identity_name}: {slug} sweep made no request for {idle:.0f}s "
                f"- WEDGED off-request, cancelling. Stuck at:\n{where}"
            ),
        )
        task.cancel()
        # Bounded wait: asyncio.wait (not await task) so an uncancellable coroutine
        # can't hang us here the way the old `await task` did.
        done, _pending = await asyncio.wait({task}, timeout=_SWEEP_CANCEL_GRACE_S)
        if task not in done:
            # The await ignored cancellation. We cannot safely continue on this event
            # loop; exit so the supervisor respawns a fresh process (fresh client too).
            raise RuntimeError(
                f"{self._identity_name}: {slug} sweep is uncancellable after "
                f"{_SWEEP_CANCEL_GRACE_S:.0f}s; exiting for respawn"
            )
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _crawl_category(self, slug: str) -> None:
        """Sweep one MONITORED category, CREATION-sorted: top N pages steady, deep by cursor.

        Listings are fetched sorted by thread CREATION date descending (the
        parser's ``by_created``), not MyBB's spam-bumpable last-post order, so
        the newest threads stay on the first pages even on a page-1-clogged
        board. In steady state (archive already backfilled) we re-sweep the top
        ``forum_steady_pages`` pages so a fresh leak that spam pushed to page 2-3
        between sweeps is still caught. Before the archive is complete, pages are
        backfilled FORWARD from a persisted cursor and the category latches
        complete at the last page. To re-backfill, reset the cursor row by hand.
        """
        _log.info("forum.category_sweep_start", identity=self._identity_name, category=slug)
        cursor_page, complete = 1, False
        if self._source_uuid is not None:
            cursor_page, complete = await self._storage.get_forum_crawl_cursor(
                source_id=self._source_uuid, category_platform_groupid=slug
            )
        # Page 1 first: newest threads, and it tells us the total page count.
        try:
            first = await self._get(
                self._parser.category_url(slug, 1, by_created=True),
                referer=self._base_url or None,
            )
        except httpx.HTTPError as exc:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.category_fetch_failed",
                message=f"{self._identity_name}: {slug} p1 failed ({exc!r})",
            )
            return
        last = self._parser.thread_page_count(first.text)
        if self._max_category_pages > 0:
            last = min(last, self._max_category_pages)
        threads = await self._process_category_page(slug, first.text)

        if complete:
            # Steady state: archive backfilled. Re-sweep the top N creation-sorted
            # pages (page 1 handled above) so a spam-sunk fresh leak is still seen.
            steady_last = min(last, self._steady_pages) if self._steady_pages > 0 else last
            for page in range(2, steady_last + 1):
                try:
                    resp = await self._get(
                        self._parser.category_url(slug, page, by_created=True),
                        referer=self._abs(slug),
                    )
                except httpx.HTTPError as exc:
                    await self.syslog(
                        level=SystemLogLevel.WARN,
                        event="forum.category_fetch_failed",
                        message=f"{self._identity_name}: {slug} p{page} failed ({exc!r})",
                    )
                    break
                threads += await self._process_category_page(slug, resp.text)
            _log.info(
                "forum.category_sweep_done",
                identity=self._identity_name,
                category=slug,
                threads=threads,
                pages=steady_last,
                mode="steady",
            )
            return

        # Backfill forward from the cursor (page 1 handled above).
        page = max(2, cursor_page)
        while page <= last:
            try:
                resp = await self._get(
                    self._parser.category_url(slug, page, by_created=True),
                    referer=self._abs(slug),
                )
            except httpx.HTTPError as exc:
                # Persist progress so the next sweep resumes here, not at page 1.
                await self._save_cursor(slug, next_page=page, complete=False)
                await self.syslog(
                    level=SystemLogLevel.WARN,
                    event="forum.category_fetch_failed",
                    message=f"{self._identity_name}: {slug} p{page} failed ({exc!r})",
                )
                return
            threads += await self._process_category_page(slug, resp.text)
            # Advance + persist after each page: a crash loses at most one page.
            await self._save_cursor(slug, next_page=page + 1, complete=page >= last)
            page += 1

        _log.info(
            "forum.category_sweep_done",
            identity=self._identity_name,
            category=slug,
            threads=threads,
            pages=last,
            mode="backfill",
        )

    async def _save_cursor(self, slug: str, *, next_page: int, complete: bool) -> None:
        if self._source_uuid is None:
            return
        await self._storage.set_forum_crawl_cursor(
            source_id=self._source_uuid,
            category_platform_groupid=slug,
            next_page=next_page,
            backfill_complete=complete,
            updated_at=datetime.now(tz=UTC),
        )

    async def _poll_thread(self, url: str, *, referer: str | None = None) -> str | None:
        """Fetch + ingest a thread; return the STABLE group key it ingested under.

        The key is resolved from the thread PAGE, not the (re-sluggable) URL: the
        page's canonical tid is bound through the alias (first-seen wins), so a
        moved/re-slugged copy resolves to the original thread's key. When a page
        yields no tid (rare), fall back to a section-prefix-normalized slug.
        Returns None if the first fetch fails (nothing ingested).
        """
        url_key = self._parser.thread_key_from_url(url)
        try:
            first = await self._get(url, referer=referer)
        except httpx.HTTPError as exc:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.fetch_failed",
                message=f"{self._identity_name}: {url} fetch failed ({exc!r})",
            )
            return None
        canonical_tid = self._parser.parse_canonical_tid(first.text)
        if canonical_tid is not None and self._source_uuid is not None:
            key = await self._storage.resolve_or_bind_forum_thread(
                source_id=self._source_uuid,
                canonical_tid=canonical_tid,
                fallback_platform_groupid=url_key,
            )
        else:
            key = _normalize_thread_slug(url_key)
        try:
            pages = self._parser.thread_page_count(first.text)
            # Cap per-thread depth: the leak announcement + download live on page 1;
            # deep pages are "thanks for the share" noise. Capping gets breadth
            # (many threads' signal) instead of deep-mining a few. 0 = all pages.
            if self._max_thread_pages > 0:
                pages = min(pages, self._max_thread_pages)
            title = self._parser.parse_thread_title(first.text)  # page 1 subject, reused
            if not title:
                await self.syslog(
                    level=SystemLogLevel.WARN,
                    event="forum.thread_title_unparsed",
                    message=f"{self._identity_name}: tid={key} - blank thread OP title "
                    "(subject selector miss), falling back to tid",
                )
            await self._ingest_page(key, title, first.text, is_first_page=True)
            for page in range(2, pages + 1):
                resp = await self._get(
                    self._parser.thread_page_url(url, page), referer=self._abs(url)
                )
                await self._ingest_page(key, title, resp.text)
        except httpx.HTTPError as exc:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.fetch_failed",
                message=f"{self._identity_name}: {url} fetch failed ({exc!r})",
            )
        return key

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
            if grp.kind is GroupKind.FORUM_CATEGORY:
                # One-shot operator override: re-sweep an explicit page RANGE of a
                # category (creation-sorted), e.g. grab page 2-3 where a fresh leak
                # sank. Defaults to page 1 if the range columns are unset.
                frm = int(getattr(req, "from_page", None) or 1)
                to = int(getattr(req, "to_page", None) or frm)
                pages = await self._backfill_category(grp.platform_groupid, frm, to)
                result = f"backfilled category pages {frm}-{to} ({pages} fetched)"
            else:
                n = await self._backfill_thread(grp.platform_groupid)
                result = f"backfilled {n} page(s)"
        except httpx.HTTPError as exc:
            await self._storage.complete_forum_backfill_request(
                req.id, state="failed", result=f"http_error:{exc!r}", completed_at=now
            )
            return
        await self._storage.complete_forum_backfill_request(
            req.id, state="done", result=result, completed_at=now
        )

    async def _backfill_category(self, slug: str, from_page: int, to_page: int) -> int:
        """Fetch a creation-sorted page RANGE of a category and ingest its threads.

        The one-shot operator override. Paced + idempotent like a normal sweep;
        put_message skips already-stored posts. Returns the page count fetched.
        """
        fetched = 0
        for page in range(max(1, from_page), max(from_page, to_page) + 1):
            resp = await self._get(
                self._parser.category_url(slug, page, by_created=True),
                referer=self._abs(slug),
            )
            await self._process_category_page(slug, resp.text)
            fetched += 1
        return fetched

    async def _backfill_thread(self, tid: str) -> int:
        """Fetch ALL pages of a thread (showthread.php?tid) and ingest them.

        Bypasses the shallow per-thread cap. put_message is insert-only, so the
        already-stored page-1 posts are skipped and the deep pages are added.
        """
        first = await self._get("showthread.php", params={"tid": tid})
        pages = self._parser.thread_page_count(first.text)
        title = self._parser.parse_thread_title(first.text)
        if not title:
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.thread_title_unparsed",
                message=f"{self._identity_name}: tid={tid} - blank thread OP title "
                "(subject selector miss), falling back to tid",
            )
        await self._ingest_page(tid, title, first.text, is_first_page=True)
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
            pages = self._parser.thread_page_count(first.text)
            for page in range(1, pages + 1):
                html = (
                    first.text
                    if page == 1
                    else (await self._get("showthread.php", params={"tid": tid, "page": page})).text
                )
                for post in self._parser.parse_thread(html):
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

    async def _ingest_page(
        self, tid: str, title: str | None, html: str, *, is_first_page: bool = False
    ) -> None:
        posts = self._parser.parse_thread(html)
        if not posts:
            _log.warning(
                "forum.empty_page",
                identity=self._identity_name,
                thread=tid,
            )
            return
        # The OP is the first post on page 1; an OP-specific anomaly (e.g. no body)
        # is a stronger signal than the same anomaly on a reply.
        for index, post in enumerate(posts):
            await self._ingest_post(tid, title, post, is_op=is_first_page and index == 0)

    async def _ingest_post(
        self, tid: str, title: str | None, post: ParsedPost, *, is_op: bool = False
    ) -> None:
        source_uuid = self._source_uuid
        if source_uuid is None:
            return
        # A blank author means our theme selector MISSED (see
        # feedback_forum_theme_variants_break_selectors). Minting an actor from an
        # empty slug yields "<board>|" and collapses every such post into ONE
        # phantom actor, silently poisoning the actor graph + stylometry. Treat it
        # as the parse failure it is: refuse the row and WARN loudly so a broken
        # theme shows up as a flood of countable syslogs, not silent bad data. The
        # post is recovered by a re-crawl once the selector is fixed (put_message
        # is insert-only, so nothing here to purge).
        if not post.author_username.strip():
            # ERROR, not WARN: attribution is non-negotiable in this field. A post with
            # no author is the data that links aliases to personas — losing it means "we
            # don't know WHO", which is unacceptable. Refuse the row AND log at top
            # severity so a theme that drops authors is impossible to miss.
            await self.syslog(
                level=SystemLogLevel.ERROR,
                event="forum.post_skipped_no_author",
                message=f"{self._identity_name}: tid={tid} pid={post.pid} parsed a blank "
                "author - selector miss, row refused (WHO is unknown)",
            )
            return
        # FAIL-CLOSED on the timestamp, BEFORE any write. An unparseable date must
        # never become now() (false recency on an old leak — CLAUDE.md 4a). Raise
        # so tick() FAULTS the collector: stop, don't backfill garbage. Nothing for
        # THIS post is written; the raw string rides the exception to the operator.
        sent_at = posted_at_to_utc(post.posted_at)
        if sent_at is None:
            raise UnparseableDateError(tid=tid, pid=post.pid, raw=post.posted_raw)
        now = datetime.now(tz=UTC)
        # Board-scope the userid: MyBB slugs collide across boards.
        platform_userid = f"{self._board}|{post.author_username}"
        key = actor_key(SourceKind.FORUM, platform_userid)

        group_id, group_changed = await self._storage.upsert_group(
            source_id=source_uuid,
            platform_groupid=tid,
            kind=GroupKind.FORUM_THREAD,
            title=title,
            seen_at=now,
        )
        if group_changed:
            await publish_entity_changed(
                self.publisher, entity_type="group", entity_id=group_id, source_id=source_uuid
            )
        actor_id, actor_changed = await self._storage.upsert_actor(
            source_id=source_uuid,
            actor_key=key,
            platform_userid=platform_userid,
            handle=post.author_display or None,
            display_name=post.author_display or None,
            seen_at=sent_at,
            is_bot=False,
        )
        if actor_changed:
            await publish_entity_changed(
                self.publisher, entity_type="actor", entity_id=actor_id, source_id=source_uuid
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

        # Empty body_html = the post_body container was missing/empty. This is NOT a
        # quote-only post (those keep their quote HTML, only body_text strips empty),
        # so it is genuinely content-less: strange for any post, and on a thread OP it
        # means the leak announcement itself did not parse. Log loud + distinct; keep
        # the row (author/metadata are valid, a re-crawl recovers the body once a
        # selector is fixed). Fires once per NEW post — the re-poll returned above.
        if not post.body_html.strip():
            await self.syslog(
                level=SystemLogLevel.WARN,
                event="forum.op_empty_body" if is_op else "forum.post_empty_body",
                message=f"{self._identity_name}: tid={tid} pid={post.pid} "
                f"{'OP' if is_op else 'post'} parsed an empty body - possible selector miss",
            )

        # (An unparseable date never reaches here — it raised UnparseableDateError
        # above, before any write, and faults the collector. No now() backfill.)

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


# Back-compat alias: the collector is engine-agnostic now (ForumCollector), but
# cli/main.py and the test suite still import the historical name.
MyBBForumCollector = ForumCollector

__all__ = ["ForumCollector", "MyBBForumCollector"]
