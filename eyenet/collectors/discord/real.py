"""DiscordCollector — gateway discovery + REST read/backfill.

SCAFFOLD. The hard, risky parts are already proven in development/poc-discord/
(DESIGN.md is the protocol spec; probe.py the REST leg; gateway.py the WS leg). This
module ports that into the CollectorSkeleton shape. Methods marked TODO are the
storage/wiring meat; the protocol logic they call is the PoC code, lift it verbatim.

Load-bearing design rules (see DESIGN.md + [[project_discord_collector_reads_upward]]):
  - Discord needs BOTH legs: WS discovers the topology (names only exist in READY),
    REST reads/backfills content by channel id.
  - Backfill walks UPWARD (before-cursor, newest->oldest). NEVER after=0 / genesis.
  - ONE coherent impersonated session across REST + WS (token + cookie + super-props +
    IDENTIFY + impersonate target all the SAME browser). curl_cffi does both.
  - User-token reads expose NO x-ratelimit headers -> pacing is timing-based, a 429 is
    the only (costly) signal: hard-stop + back off, never retry-storm.
  - Cloudflare: fail SAFE. On a challenge (not a Discord 429), PAUSE, remint cf_clearance
    via FlareSolverr, resume. We reuse the forum collector's proven challenge handling;
    the untested-in-prod path is covered by fixture tests (a captured real CF 403).
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import random
import uuid
import zlib
from datetime import UTC, datetime
from enum import Enum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from eyenet.collectors.base._credentials import DiscordSession, materialize_discord_session
from eyenet.collectors.base.skeleton import CollectorSkeleton, VisibleGroup
from eyenet.contracts.actor import actor_key
from eyenet.contracts.enums import GroupKind, MembershipRole, SourceKind, SystemLogLevel
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.models.reaction import ReactionTable
from eyenet.search_indexer.events import publish_entity_changed
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

    from eyenet.contracts.bus import Bus
    from eyenet.contracts.identity_pool import IdentityPool
    from eyenet.identity_pool.loader import IdentityFileEntry
    from eyenet.storage.repository import BaseRepository

_log = get_logger()

API = "https://discord.com/api/v9"
GATEWAY_URL = "wss://gateway.discord.gg/?encoding=json&v=9&compress=zlib-stream"
ZLIB_SUFFIX = b"\x00\x00\xff\xff"
_OP_DISPATCH = 0  # gateway op: a dispatch event (has `t` + `d`)
_OP_HELLO = 10  # gateway op: HELLO (carries heartbeat_interval)
_READABLE_CHANNEL_TYPES = (0, 5, 15)  # text, announcement, forum
_BACKFILL_PAGES_PER_TICK = 3  # bounded history walk per tick; resumes via the cursor


# --- pure mapping helpers (unit-tested; no storage / no network) --------------

def _parse_ts(iso: str | None) -> datetime | None:
    """Discord timestamps are ISO-8601 with offset. Return tz-aware UTC, or None.
    A missing/bad stamp returns None (skip the row) and NEVER now() — false recency
    on an old leak is load-bearing-wrong, same rule as the forum collector."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _actor_fields(author: dict[str, Any]) -> tuple[str, str | None, str | None, bool]:
    """(platform_userid, handle, display_name, is_bot) from a message author.
    The Discord user id (snowflake) is GLOBALLY unique, so no board-scoping needed."""
    uid = str(author.get("id") or "")
    handle = author.get("username") or None
    display = author.get("global_name") or author.get("username") or None
    return uid, handle, display, bool(author.get("bot", False))


def _build_message_row(
    *, source_id: UUID, group_id: UUID, actor_id: UUID, channel_id: str,
    msg: dict[str, Any], sent_at: datetime, now: datetime,
) -> MessageTable:
    """Message dict -> MessageTable row. evidence_ref = the snowflake (idempotent).
    Embeds/attachments/reactions/reply reference ride in source_specific; who-reacted
    and attachment blobs land later (WS events + a download pass)."""
    body = msg.get("content") or ""
    atts = msg.get("attachments") or []
    author = msg.get("author") or {}
    return MessageTable(
        id=new_uuid7(),
        source_id=source_id,
        group_id=group_id,
        actor_id=actor_id,
        platform_msgid=str(msg.get("id") or ""),
        evidence_ref=f"discord:{channel_id}:{msg.get('id')}",
        body=body,
        length_chars=len(body),
        length_words=len(body.split()),
        sent_at_source=sent_at,
        ingested_at=now,
        has_attachment=bool(atts),
        reply_to_msg_id=None,  # platform ref kept below; resolve to internal id later
        forward_of_msg_id=None,
        forward_origin_actor_id=None,
        source_specific={
            "type": msg.get("type"),
            "edited_timestamp": msg.get("edited_timestamp"),
            "author_username": author.get("username"),
            "author_global_name": author.get("global_name"),
            "message_reference": msg.get("message_reference"),  # responded_to (platform ids)
            "reactions": msg.get("reactions"),  # emoji + count (WHO reacted = WS/REST later)
            "embeds": msg.get("embeds"),
            "attachments": [
                {"id": a.get("id"), "filename": a.get("filename"), "url": a.get("url"),
                 "size": a.get("size"), "content_type": a.get("content_type")}
                for a in atts
            ],
            "mentions": [str(m.get("id")) for m in (msg.get("mentions") or [])],
        },
    )


# EXACT captured REST header order (probe.py). Accept-Encoding/Connection omitted
# (decode trap / illegal on h2). Referer is added per-request (it needs the channel).
_REST_HEADER_ORDER = (
    "User-Agent", "Accept", "Accept-Language", "Authorization", "X-Super-Properties",
    "X-Installation-Id", "X-Discord-Locale", "X-Discord-Timezone", "X-Debug-Options",
    "Alt-Used", "Cookie", "Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site",
)


def _build_rest_headers(ds: DiscordSession) -> dict[str, str]:
    """Order-preserved REST header set from the session fingerprint (same X-headers the
    captured browser sends; the WS IDENTIFY decodes the same X-Super-Properties)."""
    values = {
        "User-Agent": ds.user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Authorization": ds.token,
        "X-Super-Properties": ds.super_properties,
        "X-Installation-Id": ds.installation_id,
        "X-Discord-Locale": ds.locale,
        "X-Discord-Timezone": ds.timezone,
        "X-Debug-Options": "bugReporterEnabled",
        "Alt-Used": "discord.com",
        "Cookie": ds.cookie,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    return {k: values[k] for k in _REST_HEADER_ORDER}


_ADMINISTRATOR = 1 << 3  # Discord permission bit; a role carrying it is admin-grade


def _emoji_str(emoji: dict[str, Any]) -> str:
    """Unicode emoji -> its char; custom emoji -> 'name:id' (a stable key)."""
    name = emoji.get("name") or ""
    eid = emoji.get("id")
    return f"{name}:{eid}" if eid else name


def _reaction_from_event(d: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """(channel_id, message_id, user_id, emoji) from MESSAGE_REACTION_ADD/REMOVE, or
    None if malformed. This is the reacted_by the message object never carries."""
    ch = str(d.get("channel_id") or "")
    mid = str(d.get("message_id") or "")
    uid = str(d.get("user_id") or "")
    emoji = _emoji_str(d.get("emoji") or {})
    if not (ch and mid and uid and emoji):
        return None
    return ch, mid, uid, emoji


def _member_items(t: str, d: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize to a list of member objects (user/roles/nick/joined_at).
    GUILD_MEMBER_UPDATE is one member; GUILD_MEMBER_LIST_UPDATE nests them in
    ops[].items[].member (the lazy op14 response)."""
    if t == "GUILD_MEMBER_UPDATE":
        return [d]
    out: list[dict[str, Any]] = []
    for op in d.get("ops", []):
        for item in op.get("items", []):
            member = item.get("member")
            if member:
                out.append(member)
    return out


def _resolve_rank(
    role_ids: list[str], guild_roles: dict[str, dict[str, Any]]
) -> tuple[MembershipRole, list[str]]:
    """Join a member's role IDs against the guild role table (from READY) -> a coarse
    MembershipRole + the resolved role names. A role with the ADMINISTRATOR permission
    bit makes the member admin-grade. This is the returnero=Admin case made meaningful.
    (Guild OWNER is guild.owner_id, set separately; this resolves role-grade only.)"""
    names: list[str] = []
    admin = False
    for rid in role_ids:
        role = guild_roles.get(str(rid))
        if not role:
            continue
        names.append(role.get("name") or str(rid))
        try:
            if int(role.get("permissions", 0)) & _ADMINISTRATOR:
                admin = True
        except (TypeError, ValueError):
            pass
    return (MembershipRole.ADMIN if admin else MembershipRole.MEMBER), names


class RespClass(Enum):
    """How a gateway/REST response should be treated."""

    OK = "ok"
    DISCORD_RATE_LIMIT = "discord_429"  # Discord API: JSON retry_after
    CF_CHALLENGE = "cf_challenge"  # Cloudflare edge block: pause + remint, DO NOT retry
    AUTH_FAIL = "auth_fail"  # 401: token dead
    OTHER = "other"


class _StreamInflator:
    """Single continuous zlib context for the whole socket (compress=zlib-stream).
    A gateway message is complete at the ZLIB_SUFFIX flush. Lifted from gateway.py."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._dec = zlib.decompressobj()

    def feed(self, chunk: bytes) -> str | None:
        self._buf.extend(chunk)
        if not self._buf.endswith(ZLIB_SUFFIX):
            return None
        out = self._dec.decompress(bytes(self._buf))
        self._buf.clear()
        return out.decode("utf-8")


class DiscordCollector(CollectorSkeleton):
    """One identity = one coherent impersonated browser session, reading the guilds +
    channels that identity can see. Plural from day one (dc-coll-1, dc-coll-2, ...)."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        pool: IdentityPool,
        identity_name: str,
        session_key: Fernet | None = None,
    ) -> None:
        super().__init__(
            bus=bus, storage=storage, pool=pool,
            identity_name=identity_name, source_kind=SourceKind.DISCORD,
        )
        self._session_key = session_key  # Fernet; decrypts the session_path blob at boot
        self._session: Any = None  # curl_cffi AsyncSession(impersonate=...) for REST
        self._flare: Any = None  # FlareSolverrClient, for cf_clearance remint (optional)
        self._headers: dict[str, str] = {}  # base REST headers (Referer added per request)
        self._super_props: dict[str, Any] = {}  # decoded X-Super-Properties, for IDENTIFY
        self._capabilities = 0  # per-issuer IDENTIFY capabilities
        self._token = ""  # user token (also in _headers Authorization)
        self._source_uuid: UUID | None = None  # bound in on_subscribe
        self._collector_id: UUID | None = None  # our collector row, for membership logs
        self._channel_titles: dict[str, str] = {}  # id -> "guild / channel" from discovery
        self._guild_names: dict[str, str] = {}  # guild_id -> name (for the guild group_ node)
        self._guild_roles: dict[str, dict[str, dict[str, Any]]] = {}  # guild -> {role_id: role}
        self._channel_guild: dict[str, str] = {}  # channel_id -> guild_id (for op14 subscribe)
        self._monitored: set[str] = set()  # channel ids the operator chose; refreshed in tick
        self._gw_task: asyncio.Task[None] | None = None  # the persistent gateway stream
        self._delay_min = 1.0  # REST backfill pacing [min, max]s (from the identity entry)
        self._delay_max = 1.5
        # per-channel resume state: {channel_id: {"newest","oldest": snowflake,
        # "backfill_complete": bool}}
        self._cursors: dict[str, dict[str, Any]] = {}
        self._paused_until: float = 0.0  # monotonic; CF fail-safe backoff
        self._last_seq: int | None = None  # gateway dispatch seq, for heartbeat + resume

    # ------------------------------------------------------------------ boot

    async def on_subscribe(self) -> None:
        await super().on_subscribe()  # claims identity -> self._claimed
        entry = cast("IdentityFileEntry", self._claimed)
        # The session blob carries this issuer's FULL per-browser fingerprint: token,
        # cookie, X-Super-Properties, X-Installation-Id, UA, capabilities. REST sends the
        # X-headers; the WS IDENTIFY decodes the SAME X-Super-Properties, so both legs are
        # byte-coherent (see DESIGN.md).
        ds = materialize_discord_session(entry, self._session_key)
        self._token = ds.token
        self._capabilities = ds.capabilities
        self._super_props = json.loads(base64.b64decode(ds.super_properties))
        self._headers = _build_rest_headers(ds)
        # curl_cffi impersonated session (TLS matches the token's browser). Lazy import:
        # only the clearnet path needs curl-cffi.
        from curl_cffi.requests import AsyncSession  # noqa: PLC0415

        self._session = AsyncSession(impersonate=entry.discord_impersonate, timeout=30.0)
        # TODO: when entry.discord_enable_waf_bypass, build a FlareSolverrClient on
        # self._flare for cf_clearance reminting (see _remint_clearance).
        # Ingest into the source the operator chose at collector-creation; never
        # auto-create one (mirrors the forum collector).
        self._delay_min = float(entry.discord_delay_min)
        self._delay_max = float(entry.discord_delay_max)
        collector = await self._storage.resolve_collector_by_instance_id(self.instance_id)
        self._collector_id = collector.id if collector is not None else None
        if collector is not None:
            self._source_uuid = collector.source_id
        self._monitored = set(await self._monitored_channels())  # for READY op14 + live gate
        # Launch the persistent gateway stream (live events = the diamond). tick() drives
        # the REST history backfill separately.
        self._gw_task = asyncio.create_task(self._run_gateway())

    async def stop(self) -> None:
        if self._gw_task is not None:
            self._gw_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._gw_task
        await super().stop()

    # ---------------------------------------------------- discovery: gateway WS

    async def enumerate_visible_groups(self) -> list[VisibleGroup]:
        """Gateway READY -> every viewable channel as a VisibleGroup. The base
        scan_visible_groups turns these into GroupCandidates. Channel NAMES only exist
        here (the REST message fetch has none), so we carry them in .title."""
        ready = await self._gateway_ready()
        self._cache_from_ready(ready)
        out: list[VisibleGroup] = []
        for g in ready.get("guilds", []):
            gid = str(g.get("id") or "")
            if gid:
                out.append(VisibleGroup(  # the guild itself is a container node
                    platform_groupid=gid, kind=GroupKind.GUILD,
                    title=self._guild_names.get(gid), is_member=True,
                ))
            for c in g.get("channels", []):
                if c.get("type") in _READABLE_CHANNEL_TYPES and self._can_view(g, c):
                    cid = str(c["id"])
                    out.append(VisibleGroup(
                        platform_groupid=cid, kind=GroupKind.CHANNEL,
                        title=self._channel_titles.get(cid), is_member=True,
                    ))
        _log.info("discord.discovery", guilds=len(ready.get("guilds", [])), channels=len(out))
        return out

    def _cache_from_ready(self, ready: dict[str, Any]) -> None:
        """Populate the in-memory maps from a READY payload: guild names/roles, channel
        titles, and channel->guild (needed to label groups + target op14 subscribes).
        Shared by discovery and the live stream, both of which get a READY."""
        for g in ready.get("guilds", []):
            gid = str(g.get("id") or "")
            if not gid:
                continue
            name = g.get("properties", {}).get("name") or g.get("name") or gid
            self._guild_names[gid] = name
            self._cache_guild_roles(g)
            for c in g.get("channels", []):
                cid = str(c.get("id") or "")
                if not cid:
                    continue
                self._channel_guild[cid] = gid
                if c.get("type") in _READABLE_CHANNEL_TYPES:
                    self._channel_titles[cid] = f"{name} / {c.get('name', '?')}"

    async def _gateway_ready(self) -> dict[str, Any]:
        """One-shot: connect, IDENTIFY, read until READY, return its payload, close.
        Discovery (enumerate_visible_groups) rides this. Clean async over curl_cffi's
        AsyncWebSocket; the persistent live stream is _run_gateway."""
        inflator = _StreamInflator()
        async with self._session.ws_connect(
            GATEWAY_URL, headers=self._ws_headers(), default_headers=False
        ) as ws:
            hello = await self._ws_recv(ws, inflator)
            if not hello or hello.get("op") != _OP_HELLO:
                raise RuntimeError(f"{self._identity_name}: expected gateway HELLO, got {hello}")
            await self._ws_identify(ws)
            deadline = asyncio.get_event_loop().time() + 30.0
            while asyncio.get_event_loop().time() < deadline:
                msg = await self._ws_recv(ws, inflator)
                if msg is None:
                    break
                if msg.get("op") == _OP_DISPATCH and msg.get("t") == "READY":
                    return dict(msg.get("d") or {})
        raise RuntimeError(f"{self._identity_name}: no gateway READY within 30s")

    def _ws_headers(self) -> dict[str, str]:
        """Upgrade headers for the gateway WS: UA + cookie (cf_clearance) from the same
        session, Origin discord.com. TLS fingerprint comes from the session's impersonate."""
        return {
            "User-Agent": self._headers.get("User-Agent", ""),
            "Origin": "https://discord.com",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": self._headers.get("Cookie", ""),
        }

    async def _ws_identify(self, ws: Any) -> None:
        """Send IDENTIFY (properties = this session's decoded X-Super-Properties) + the
        proprietary op-41 init the real client emits right after."""
        await ws.send(json.dumps(
            self._build_identify(self._super_props, self._token, capabilities=self._capabilities)
        ))
        await ws.send(json.dumps({"op": 41, "d": {
            "initialization_timestamp": int(datetime.now(tz=UTC).timestamp() * 1000),
            "session_id": str(uuid.uuid4()),
            "client_launch_id": str(uuid.uuid4()),
        }}))

    @staticmethod
    async def _ws_recv(ws: Any, inflator: _StreamInflator) -> dict[str, Any] | None:
        """Recv frames until a full inflated gateway message, parse JSON. None on close."""
        while True:
            raw = await ws.recv()
            if isinstance(raw, tuple):
                raw = raw[0]
            if raw is None:
                return None
            if not raw:
                continue
            text = inflator.feed(raw)
            if text is not None:
                return cast("dict[str, Any]", json.loads(text))

    @staticmethod
    def _can_view(_guild: dict[str, Any], _channel: dict[str, Any]) -> bool:
        # TODO: compute VIEW_CHANNEL from member roles + channel permission_overwrites.
        # Firing a read at a channel we cannot see = 403 = a flare. Default-deny when unsure.
        return True

    # -------------------------------------------------------- read / backfill

    async def tick(self) -> None:
        """Drive REST HISTORY backfill of monitored channels, a bounded chunk per tick
        (resumable via the cursor). Live messages arrive on the gateway stream, so tick
        does not poll for them. Honors the CF/429 pause."""
        if self._session is None or self._source_uuid is None:
            return
        if asyncio.get_event_loop().time() < self._paused_until:
            return
        self._monitored = set(await self._monitored_channels())  # refresh the live gate
        for channel_id in self._monitored:
            if self._cursors.get(channel_id, {}).get("backfill_complete"):
                continue  # history done; the gateway handles everything newer
            await self._backfill_channel(channel_id, max_pages=_BACKFILL_PAGES_PER_TICK)

    async def _monitored_channels(self) -> list[str]:
        """Channel ids the operator chose to monitor = this collector's active
        memberships filtered to CHANNEL groups (a DB read; opening one is a manual
        operator action, never automatic). Fail-closed if none."""
        if self._collector_id is None:
            return []
        out: list[str] = []
        for m in await self._storage.list_active_memberships(collector_id=self._collector_id):
            grp = await self._storage.get_group(m.group_id)
            if grp is not None and grp.kind == GroupKind.CHANNEL:
                out.append(grp.platform_groupid)
        return out

    async def _backfill_channel(
        self, channel_id: str, *, limit: int = 100, max_pages: int = 0
    ) -> int:
        """UPWARD before-walk (newest->oldest); NEVER after=0. Ingest each page, persist
        oldest_seen as the resume cursor, mark backfill_complete at the channel start.
        Paces each inter-page gap by the identity's [delay_min, delay_max] jitter.
        Returns the count ingested this call."""
        cur = self._cursors.setdefault(channel_id, {})
        before = cur.get("oldest")
        pages = total = 0
        while max_pages == 0 or pages < max_pages:
            if asyncio.get_event_loop().time() < self._paused_until:
                break
            batch = await self._rest_messages(channel_id, before=before, limit=limit)
            if not batch:
                break
            pages += 1
            total += len(batch)
            for msg in batch:
                await self._ingest_message(channel_id, msg)
            before = str(batch[-1]["id"])
            cur["oldest"] = before
            cur.setdefault("newest", str(batch[0]["id"]))  # first page's top = newest seen
            if len(batch) < limit:
                cur["backfill_complete"] = True  # reached channel start
                break
            await asyncio.sleep(self._jitter(self._delay_min, self._delay_max))
        return total

    async def _rest_messages(
        self, channel_id: str, *, before: str | None = None,
        after: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /channels/{id}/messages with the coherent impersonated headers. Classify
        the response: a Cloudflare challenge pauses + remints, a Discord 429 backs off.
        Returns the message list on OK, [] otherwise."""
        qs = f"?limit={limit}"
        if before:
            qs += f"&before={before}"
        if after:
            qs += f"&after={after}"
        headers = {**self._headers, "Referer": f"https://discord.com/channels/@me/{channel_id}"}
        r = await self._session.get(
            f"{API}/channels/{channel_id}/messages{qs}", headers=headers, default_headers=False
        )
        status = int(r.status_code)
        cls = self._classify(status, dict(r.headers), "" if status == HTTPStatus.OK else r.text)
        if cls is RespClass.OK:
            return list(r.json())
        if cls is RespClass.CF_CHALLENGE:
            await self._remint_clearance()  # pauses the collector; never retry blind
            return []
        if cls is RespClass.DISCORD_RATE_LIMIT:
            ct = r.headers.get("content-type", "")
            data = r.json() if ct.startswith("application/json") else {}
            retry = float(data.get("retry_after", 5))
            self._paused_until = asyncio.get_event_loop().time() + retry
            _log.warning("discord.rate_limited", channel=channel_id, retry_after=retry)
            return []
        if cls is RespClass.AUTH_FAIL:
            raise RuntimeError(f"{self._identity_name}: Discord token rejected (401)")
        _log.warning("discord.rest_unexpected", channel=channel_id, status=status)
        return []

    # ---------------------------------------------------- cloudflare fail-safe

    def _classify(self, status: int, headers: dict[str, str], body: str) -> RespClass:
        """Discord 429 (JSON retry_after) vs a Cloudflare edge block. The two need
        different handling, so never conflate them."""
        if status == HTTPStatus.UNAUTHORIZED:
            return RespClass.AUTH_FAIL
        ct = headers.get("content-type", "")
        cf = "cf-ray" in {k.lower() for k in headers}
        is_json = "application/json" in ct
        if status in (HTTPStatus.FORBIDDEN, HTTPStatus.SERVICE_UNAVAILABLE) and cf and not is_json:
            return RespClass.CF_CHALLENGE  # managed challenge / clearance expired
        if status == HTTPStatus.TOO_MANY_REQUESTS:
            # Cloudflare 429 is HTML+cf-ray; Discord 429 is JSON retry_after.
            return RespClass.DISCORD_RATE_LIMIT if is_json else RespClass.CF_CHALLENGE
        if any(m in body for m in ("__cf_chl", "cf-mitigated", "challenge-platform")):
            return RespClass.CF_CHALLENGE
        return RespClass.OK if status == HTTPStatus.OK else RespClass.OTHER

    async def _remint_clearance(self) -> None:
        """Fail-safe: pause the collector, mint a fresh cf_clearance in a real browser
        via FlareSolverr, splice it + the returned UA into the session, resume. Pausing
        is always safe; blind retry escalates a challenge into a ban."""
        self._paused_until = asyncio.get_event_loop().time() + 60.0
        if self._flare is None:
            _log.warning("discord.cf_challenge.no_flaresolverr")
            return
        # TODO: resp = await self._flare.get("https://discord.com/"); extract cf_clearance
        #   (+ __cf_bm) and UA; update the Cookie header + impersonate coherently; clear pause.
        raise NotImplementedError("FlareSolverr cf_clearance remint")

    # ------------------------------------------------------------- ingest

    async def _ingest_message(self, channel_id: str, msg: dict[str, Any]) -> None:
        """Map a Discord message -> actor(author) + group(channel) + message. Idempotent
        on the snowflake evidence_ref. Embeds/attachments/reactions/reply reference ride in
        source_specific (who-reacted + attachment blobs are later passes). Bots/drop-bots
        put the payload in embeds, not content, so both are kept."""
        source_uuid = self._source_uuid
        if source_uuid is None:
            return
        uid, handle, display, is_bot = _actor_fields(msg.get("author") or {})
        if not uid:  # no author id -> cannot attribute; WHO is non-negotiable
            await self.syslog(
                level=SystemLogLevel.ERROR,
                event="discord.msg_skipped_no_author",
                message=f"{self._identity_name}: channel={channel_id} msg={msg.get('id')} "
                "no author id, row refused",
            )
            return
        # Discord always stamps; a missing one is malformed -> skip, never now().
        sent_at = _parse_ts(msg.get("timestamp"))
        if sent_at is None:
            return
        now = datetime.now(tz=UTC)

        group_id, group_changed = await self._storage.upsert_group(
            source_id=source_uuid,
            platform_groupid=str(channel_id),
            kind=GroupKind.CHANNEL,
            title=self._channel_titles.get(str(channel_id)),
            seen_at=now,
        )
        if group_changed:
            await publish_entity_changed(
                self.publisher, entity_type="group", entity_id=group_id, source_id=source_uuid
            )
        actor_id, actor_changed = await self._storage.upsert_actor(
            source_id=source_uuid,
            actor_key=actor_key(SourceKind.DISCORD, uid),
            platform_userid=uid,
            handle=handle,
            display_name=display,
            seen_at=sent_at,
            is_bot=is_bot,
        )
        if actor_changed:
            await publish_entity_changed(
                self.publisher, entity_type="actor", entity_id=actor_id, source_id=source_uuid
            )

        row = _build_message_row(
            source_id=source_uuid, group_id=group_id, actor_id=actor_id,
            channel_id=str(channel_id), msg=msg, sent_at=sent_at, now=now,
        )
        # TODO: pass real AttachmentTable rows once the blob-download pass lands; for now
        # attachment metadata is in source_specific (has_attachment set, bytes deferred).
        if await self._storage.put_message(row, []):
            self._record_emission()

    # ------------------------------------------------ gateway dispatch loop

    async def _run_gateway(self) -> None:
        """Persistent live stream: connect, IDENTIFY, heartbeat, consume dispatches,
        reconnect on drop. Runs until stop(). The diamond feeds on this."""
        while not self.stop_event.is_set():
            inflator = _StreamInflator()
            try:
                async with self._session.ws_connect(
                    GATEWAY_URL, headers=self._ws_headers(), default_headers=False
                ) as ws:
                    hello = await self._ws_recv(ws, inflator)
                    if not hello or hello.get("op") != _OP_HELLO:
                        raise RuntimeError(f"{self._identity_name}: gateway sent no HELLO")
                    interval = float(hello["d"]["heartbeat_interval"]) / 1000.0
                    await self._ws_identify(ws)
                    hb = asyncio.create_task(self._heartbeat(ws, interval))
                    try:
                        await self._consume_gateway(ws, inflator)
                    finally:
                        hb.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await hb
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.warning(
                    "discord.gateway.reconnect", identity=self._identity_name, error=str(exc)
                )
                await asyncio.sleep(self._jitter(3.0, 8.0))

    async def _heartbeat(self, ws: Any, interval: float) -> None:
        """op1 every HELLO interval, jittered; carries last_seq. Miss it and we're dropped."""
        await asyncio.sleep(interval * random.uniform(0.85, 1.0))  # noqa: S311  (jitter)
        while not self.stop_event.is_set():
            await ws.send(json.dumps({"op": 1, "d": self._last_seq}))
            await asyncio.sleep(interval * random.uniform(0.9, 1.0))  # noqa: S311  (jitter)

    async def _consume_gateway(self, ws: Any, inflator: _StreamInflator) -> None:
        """recv -> inflate -> route. On READY, cache the tree + op14-subscribe monitored
        channels so member lists stream. The 'diamond': reactions, members, live messages
        become model here."""
        while not self.stop_event.is_set():
            msg = await self._ws_recv(ws, inflator)
            if msg is None:
                return  # socket closed -> _run_gateway reconnects
            if msg.get("s") is not None:
                self._last_seq = int(msg["s"])
            if msg.get("op") != _OP_DISPATCH:
                continue
            t, d = msg.get("t"), msg.get("d") or {}
            if t == "READY":
                self._cache_from_ready(d)
                await self._subscribe_members(ws)
            elif t:
                await self._dispatch(str(t), d)

    async def _subscribe_members(self, ws: Any) -> None:
        """op14: subscribe to each monitored channel's member list so
        GUILD_MEMBER_LIST_UPDATE (the ranks) streams in. Grouped per guild."""
        by_guild: dict[str, list[str]] = {}
        for cid in self._monitored:
            gid = self._channel_guild.get(cid)
            if gid:
                by_guild.setdefault(gid, []).append(cid)
        for gid, cids in by_guild.items():
            await ws.send(json.dumps({"op": 14, "d": {
                "guild_id": gid, "typing": True, "activities": True, "threads": False,
                "channels": {cid: [[0, 99]] for cid in cids},
            }}))

    async def _dispatch(self, t: str, d: dict[str, Any]) -> None:
        """Route one gateway dispatch. Message + reaction ingest is gated on the monitored
        channel set; member/role events are already scoped by the op14 subscribes we sent."""
        if t in ("MESSAGE_CREATE", "MESSAGE_UPDATE"):
            ch = str(d.get("channel_id") or "")
            if ch in self._monitored:
                await self._ingest_message(ch, d)
        elif t == "MESSAGE_REACTION_ADD":
            if str(d.get("channel_id") or "") in self._monitored:
                await self._handle_reaction(d)
        elif t in ("GUILD_MEMBER_LIST_UPDATE", "GUILD_MEMBER_UPDATE"):
            await self._handle_members(t, d)
        elif t in ("GUILD_ROLE_CREATE", "GUILD_ROLE_UPDATE", "GUILD_ROLE_DELETE"):
            self._handle_role(t, d)
        elif t == "GUILD_CREATE":
            self._cache_guild_roles(d)  # roles + channels arrive on join
        # PRESENCE_UPDATE / TYPING_START: ephemeral; ignored for now (TODO: last-seen)

    async def _handle_reaction(self, d: dict[str, Any]) -> None:
        """reacted_by: who reacted to what. Needs the target message already stored
        (resolve by snowflake). Reaction events carry no timestamp, so a LIVE event's
        time is now() — correct here, it is a real-time dispatch."""
        source_uuid = self._source_uuid
        parsed = _reaction_from_event(d)
        if source_uuid is None or parsed is None:
            return
        channel_id, message_id, user_id, emoji = parsed
        now = datetime.now(tz=UTC)
        group_id, _ = await self._storage.upsert_group(
            source_id=source_uuid, platform_groupid=channel_id, kind=GroupKind.CHANNEL,
            title=self._channel_titles.get(channel_id), seen_at=now,
        )
        target = await self._storage.resolve_message_id(
            source_id=source_uuid, group_id=group_id, platform_msgid=message_id,
        )
        if target is None:
            _log.debug("discord.reaction.target_unknown", message=message_id, emoji=emoji)
            return  # reaction to a message we have not stored; drop
        actor_id, _ = await self._storage.upsert_actor(
            source_id=source_uuid, actor_key=actor_key(SourceKind.DISCORD, user_id),
            platform_userid=user_id, handle=None, display_name=None, seen_at=now,
        )
        row = ReactionTable(
            id=new_uuid7(), message_id=target, actor_id=actor_id, emoji=emoji,
            reacted_at=now, evidence_ref=f"discord:reaction:{message_id}:{user_id}:{emoji}",
        )
        async with self._storage.session() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()  # idempotent re-delivery on evidence_ref

    async def _handle_members(self, t: str, d: dict[str, Any]) -> None:
        """member.roles x guild.roles -> each member's rank, persisted as an actor<->guild
        membership (the diamond: returnero=Admin becomes a membership row). The guild is
        its own GroupKind.GUILD group_ node; rank lands via upsert_membership."""
        source_uuid = self._source_uuid
        guild_id = str(d.get("guild_id") or "")
        if source_uuid is None or not guild_id:
            return
        guild_roles = self._guild_roles.get(guild_id, {})
        now = datetime.now(tz=UTC)
        group_id, group_changed = await self._storage.upsert_group(
            source_id=source_uuid, platform_groupid=guild_id, kind=GroupKind.GUILD,
            title=self._guild_names.get(guild_id), seen_at=now,
        )
        if group_changed:
            await publish_entity_changed(
                self.publisher, entity_type="group", entity_id=group_id, source_id=source_uuid
            )
        for member in _member_items(t, d):
            user = member.get("user") or {}
            uid = str(user.get("id") or "")
            if not uid:
                continue
            rank, _names = _resolve_rank(
                [str(r) for r in (member.get("roles") or [])], guild_roles
            )
            actor_id, actor_changed = await self._storage.upsert_actor(
                source_id=source_uuid, actor_key=actor_key(SourceKind.DISCORD, uid),
                platform_userid=uid, handle=user.get("username") or None,
                display_name=user.get("global_name") or user.get("username") or None,
                seen_at=now, is_bot=bool(user.get("bot", False)),
            )
            if actor_changed:
                await publish_entity_changed(
                    self.publisher, entity_type="actor", entity_id=actor_id, source_id=source_uuid
                )
            await self._storage.upsert_membership(
                actor_id=actor_id, group_id=group_id, role=rank, seen_at=now
            )

    def _cache_guild_roles(self, guild: dict[str, Any]) -> None:
        gid = str(guild.get("id") or "")
        if gid:
            self._guild_roles[gid] = {
                str(r["id"]): r for r in guild.get("roles", []) if r.get("id")
            }

    def _handle_role(self, t: str, d: dict[str, Any]) -> None:
        roles = self._guild_roles.setdefault(str(d.get("guild_id") or ""), {})
        if t == "GUILD_ROLE_DELETE":
            roles.pop(str(d.get("role_id") or ""), None)
        else:
            role = d.get("role") or {}
            if role.get("id"):
                roles[str(role["id"])] = role

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _build_identify(
        super_props: dict[str, Any], token: str, *, capabilities: int
    ) -> dict[str, Any]:
        """IDENTIFY op2. `properties` MUST be the base64-DECODE of THIS session's
        `X-Super-Properties` header (the same fingerprint REST sends) so the two legs are
        byte-coherent — we do NOT reconstruct it. Only the per-launch ids regenerate.
        `super_props` + `capabilities` come from the session blob (per issuer)."""
        props = {
            **super_props,
            "client_launch_id": str(uuid.uuid4()),
            "launch_signature": str(uuid.uuid4()),
            "client_app_state": "focused",
        }
        return {"op": 2, "d": {
            "token": token,
            "capabilities": capabilities,
            "properties": props,
            "presence": {"status": "unknown", "since": 0, "activities": [], "afk": False},
            "compress": False, "client_state": {"guild_versions": {}}, "qos_token": "CgIIAQ==",
        }}

    @staticmethod
    def _jitter(lo: float, hi: float) -> float:
        return random.uniform(lo, hi)  # noqa: S311  (pacing jitter, not crypto)
