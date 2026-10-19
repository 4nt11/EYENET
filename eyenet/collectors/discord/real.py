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
import random
import uuid
import zlib
from enum import Enum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, cast

from eyenet.collectors.base.skeleton import CollectorSkeleton, VisibleGroup
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from eyenet.contracts.bus import Bus
    from eyenet.contracts.identity_pool import IdentityPool
    from eyenet.identity_pool.loader import IdentityFileEntry
    from eyenet.storage.repository import BaseRepository

_log = get_logger()

API = "https://discord.com/api/v9"
GATEWAY_URL = "wss://gateway.discord.gg/?encoding=json&v=9&compress=zlib-stream"
ZLIB_SUFFIX = b"\x00\x00\xff\xff"
_READABLE_CHANNEL_TYPES = (0, 5, 15)  # text, announcement, forum


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
    ) -> None:
        super().__init__(
            bus=bus, storage=storage, pool=pool,
            identity_name=identity_name, source_kind=SourceKind.DISCORD,
        )
        self._session: Any = None  # curl_cffi.requests.Session(impersonate=...), REST + WS
        self._flare: Any = None  # FlareSolverrClient, for cf_clearance remint (optional)
        self._headers: dict[str, str] = {}
        # per-channel resume cursors: {channel_id: {"newest": snowflake, "oldest": snowflake}}
        self._cursors: dict[str, dict[str, str]] = {}
        self._paused_until: float = 0.0  # monotonic; CF fail-safe backoff

    # ------------------------------------------------------------------ boot

    async def on_subscribe(self) -> None:
        await super().on_subscribe()  # claims identity -> self._claimed
        entry = cast("IdentityFileEntry", self._claimed)
        # The claimed entry carries session_path (Fernet-encrypted token + cookie jar,
        # same seam as telegram) plus the discord_* fingerprint and pacing knobs. Build
        # ONE curl_cffi impersonated Session (impersonate=entry.discord_impersonate) and
        # the order-preserved REST header set (see probe.py build_headers; Accept-Encoding
        # and Connection omitted). The impersonate target MUST match the token's browser.
        # When entry.discord_enable_waf_bypass is set, keep a FlareSolverrClient (from
        # eyenet.collectors.forum._flaresolverr) on self._flare for cf_clearance reminting.
        raise NotImplementedError(
            f"build the impersonated session for {entry.name} from its identity blob"
        )

    # ---------------------------------------------------- discovery: gateway WS

    async def enumerate_visible_groups(self) -> list[VisibleGroup]:
        """Gateway READY -> every viewable channel as a VisibleGroup. The base
        scan_visible_groups turns these into GroupCandidates. Channel NAMES only exist
        here (the REST message fetch has none), so we carry them in .title."""
        ready = await self._gateway_ready()
        out: list[VisibleGroup] = []
        for g in ready.get("guilds", []):
            gname = g.get("properties", {}).get("name") or g.get("name") or g.get("id")
            for c in g.get("channels", []):
                if c.get("type") in _READABLE_CHANNEL_TYPES and self._can_view(g, c):
                    out.append(VisibleGroup(
                        platform_groupid=str(c["id"]),
                        kind=GroupKind.CHANNEL,
                        title=f"{gname} / {c.get('name', '?')}",
                        is_member=True,
                    ))
        _log.info("discord.discovery", guilds=len(ready.get("guilds", [])), channels=len(out))
        return out

    async def _gateway_ready(self) -> dict[str, Any]:
        """Native WS connect -> HELLO -> IDENTIFY(+op41) -> heartbeat -> read until
        READY, then close. Port gateway.py: _StreamInflator + build_identify + the
        recv/inflate loop, over self._session.ws_connect(GATEWAY_URL, impersonate=...)
        with the Cookie/Origin headers. Classify a non-101 upgrade via _classify."""
        # TODO: lift gateway.py run() body (minus the printing) and return msg["d"].
        raise NotImplementedError("port gateway.py gateway handshake -> READY payload")

    @staticmethod
    def _can_view(_guild: dict[str, Any], _channel: dict[str, Any]) -> bool:
        # TODO: compute VIEW_CHANNEL from member roles + channel permission_overwrites.
        # Firing a read at a channel we cannot see = 403 = a flare. Default-deny when unsure.
        return True

    # -------------------------------------------------------- read / backfill

    async def tick(self) -> None:
        """Per monitored channel: live catch-up (after=newest_seen) + drain any
        operator backfill requests. Human-brisk pacing; honor _paused_until."""
        if asyncio.get_event_loop().time() < self._paused_until:
            return
        # TODO: for each monitored (promoted) channel:
        #   - live: _rest_messages(ch, after=self._cursors[ch]["newest"]) -> ingest, advance newest
        #   - backfill: drain forum-style backfill requests via _backfill_channel
        raise NotImplementedError("wire monitored-channel catch-up + backfill drain")

    async def _backfill_channel(
        self, channel_id: str, *, delay: float, limit: int = 100, max_pages: int = 0
    ) -> int:
        """UPWARD before-walk (newest->oldest). NEVER after=0. 429 = hard stop. Lifted
        from probe.py --backfill; ingest each page, persist oldest_seen as the resume
        cursor, stop on a short page (channel start)."""
        # TODO: port probe.backfill loop; call _ingest_message per message; sleep(delay)
        #   jittered between pages; update self._cursors[channel_id]["oldest"].
        raise NotImplementedError("port probe.py backfill (upward)")

    async def _rest_messages(
        self, channel_id: str, *, before: str | None = None,
        after: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /channels/{id}/messages with the coherent impersonated headers.
        Classify the response; on CF_CHALLENGE pause+remint, on DISCORD_RATE_LIMIT
        hard-stop+back off. Returns the message list on OK."""
        # TODO: self._session.get(url, headers=self._headers, impersonate=...,
        #   default_headers=False); then _classify; act; return r.json() on OK.
        raise NotImplementedError("port probe.py fetch + response classification")

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
        """Map a Discord message -> actor(author) + group(channel) + message, with
        embeds + attachments. evidence_ref = the message snowflake (idempotent). Bots/
        drop-bots carry the payload in embeds, not content — ingest both."""
        # Upsert the author actor (id/username/bot flag), ensure the channel group, then
        # storage.put_message with evidence_ref = the snowflake and sent_at_source parsed
        # from msg["timestamp"]; store embeds (title/description/fields) + attachments.
        _log.debug("discord.ingest.todo", channel=channel_id, msg_id=msg.get("id"))
        self._record_emission()
        raise NotImplementedError("map message -> storage.put_message + embeds/attachments")

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _build_identify(entry: IdentityFileEntry, token: str) -> dict[str, Any]:
        """IDENTIFY op2 — mirror the captured client frame; fresh launch ids per connect,
        stable installation_id. See gateway.build_identify / DESIGN.md."""
        return {"op": 2, "d": {
            "token": token,
            "capabilities": 1734653,
            "properties": {
                "os": "Linux", "browser": "Chrome", "device": "",
                "browser_user_agent": entry.discord_user_agent or "",
                "release_channel": "stable",
                "client_build_number": entry.discord_build_number,
                "client_launch_id": str(uuid.uuid4()),
                "launch_signature": str(uuid.uuid4()),
                "client_app_state": "focused",
                "gateway_connect_reasons": "AppSkeleton",
                "installation_id": entry.discord_installation_id or "",
            },
            "presence": {"status": "unknown", "since": 0, "activities": [], "afk": False},
            "compress": False, "client_state": {"guild_versions": {}}, "qos_token": "CgIIAQ==",
        }}

    @staticmethod
    def _jitter(lo: float, hi: float) -> float:
        return random.uniform(lo, hi)  # noqa: S311  (pacing jitter, not crypto)
