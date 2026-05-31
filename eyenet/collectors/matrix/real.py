"""`MatrixCollector` — real matrix-nio-based message collector.

One process = one identity = all rooms that identity is joined to. Mirrors
the Telegram collector's design (PLAN §2.1 scoping rule): one collector
multiplexes all monitored rooms onto the bus.

Auth: pre-provisioned `matrix_access_token` from the identity TOML. No
login round-trip at start.

M8 scope:
- Text events (`RoomMessageText`) + media events (image/file/video/audio +
  stickers) — attachments are downloaded, decrypted if needed, hash-verified,
  and persisted to disk via `eyenet.storage.attachments.store_attachment`.
- E2EE: `AsyncClientConfig(encryption_enabled=True)` + persistent
  SqliteStore at `matrix_device_store_path`. `MegolmEvent` is decrypted via
  `client.decrypt_event`; failures emit a sentinel envelope so operators
  see the undecryptable count without losing the event id.
- Relations: `m.in_reply_to` (FK best-effort via `resolve_message_id`),
  `m.replace` edits (history appended to `source_specific.edits`),
  `m.reaction` annotations (new `ReactionTable`).
- Backfill via `/messages` pagination is supported when started with
  `backfill=True` AND `matrix_monitor_rooms` is non-empty. Pages backwards
  from the latest sync token until the per-room limit is hit or the room
  is exhausted. Live + backfill dedupe at MessageStore via evidence_ref.

OPSEC: Matrix has no "invisible" presence — `offline` is the invisible
state. Hard-coded on every sync. See
[[feedback_matrix_collector_offline_only]].
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time as _time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import structlog
from nio import (
    AsyncClient,
    AsyncClientConfig,
    BadEvent,
    MatrixRoom,
    MegolmEvent,
    MessageDirection,
    ReactionEvent,
    RoomMessageAudio,
    RoomMessageFile,
    RoomMessageImage,
    RoomMessagesError,
    RoomMessagesResponse,
    RoomMessageText,
    RoomMessageVideo,
    RoomResolveAliasError,
    RoomResolveAliasResponse,
    SyncResponse,
    UnknownBadEvent,
    WhoamiError,
    WhoamiResponse,
)
from nio.crypto.attachments import decrypt_attachment
from opentelemetry import trace
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from eyenet.collectors.base.skeleton import CollectorSkeleton
from eyenet.contracts._base import TraceContext
from eyenet.contracts.bus import Bus
from eyenet.contracts.collector import CollectorHealth
from eyenet.contracts.classify_events import (
    SUBJECT_ATTACHMENT_STORED,
    AttachmentStoredEnvelope,
)
from eyenet.contracts.enums import (
    AttachmentKind,
    CollectorState,
    GroupKind,
    IdentityState,
    SensitivityTier,
    SourceKind,
)
from eyenet.contracts.identity_pool import IdentityPool
from eyenet.contracts.raw_message import RawMessageEnvelope, subject_for
from eyenet.identity_pool.loader import IdentityFileEntry
from eyenet.models import AttachmentTable, GroupTable, MessageTable, ReactionTable
from eyenet.models._base import new_uuid7
from eyenet.storage import store_attachment
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.propagation import current_traceparent

_log = structlog.get_logger()
_tracer = trace.get_tracer("eyenet.collector.matrix")

# max subscriptions returned in health()
_HEALTH_SUBS_CAP = 100
# nio sync_forever loop timeout (ms)
_SYNC_TIMEOUT_MS = 30_000
# Initial one-shot sync timeout (ms) — used to populate client.rooms and the
# per-room prev_batch token before backfill kicks off.
_INITIAL_SYNC_TIMEOUT_MS = 5_000
# Page size for /messages pagination during backfill. Matrix spec recommends
# <= 100 per request; some homeservers cap lower.
_BACKFILL_PAGE_SIZE = 100
# Default cap on total events ingested per backfilled room.
_DEFAULT_BACKFILL_LIMIT_PER_ROOM = 1000
# OPSEC: Matrix has no separate "invisible" presence — "offline" is the
# invisible state. Hard-coded.
_PRESENCE_OFFLINE = "offline"


def _zero_traceparent() -> str:
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


# msgtype -> AttachmentKind. Voice notes are AUDIO with the MSC3245 hint;
# detection happens in `_attachment_kind_for_event` rather than via msgtype.
_MEDIA_MSGTYPE_KIND: dict[type[Any], AttachmentKind] = {
    RoomMessageImage: AttachmentKind.IMAGE,
    RoomMessageFile: AttachmentKind.DOCUMENT,
    RoomMessageVideo: AttachmentKind.VIDEO,
    RoomMessageAudio: AttachmentKind.AUDIO,
}

# msgtype string -> AttachmentKind. Used for synthetic events / decrypted
# payloads where the Python class isn't one of nio's RoomMessage* types.
_MSGTYPE_KIND: dict[str, AttachmentKind] = {
    "m.image": AttachmentKind.IMAGE,
    "m.video": AttachmentKind.VIDEO,
    "m.audio": AttachmentKind.AUDIO,
    "m.file": AttachmentKind.DOCUMENT,
    "m.sticker": AttachmentKind.STICKER,
}


class MatrixCollector(CollectorSkeleton):
    """matrix-nio-based real Matrix collector with E2EE + attachments."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        pool: IdentityPool,
        identity_name: str,
        backfill: bool = False,
        backfill_limit: int = _DEFAULT_BACKFILL_LIMIT_PER_ROOM,
    ) -> None:
        super().__init__(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name=identity_name,
            source_kind=SourceKind.MATRIX,
        )
        self._client: AsyncClient | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._backfill_task: asyncio.Task[None] | None = None
        self._source_uuid: UUID | None = None
        self._monitor_room_ids: set[str] = set()
        self._recent: deque[float] = deque(maxlen=3600)
        self._backfill = backfill
        self._backfill_limit = backfill_limit
        self._device_store_path: Path | None = None
        # nio downgrades any event that fails its strict jsonschema to
        # BadEvent / UnknownBadEvent and keeps delivering. The console
        # log line is suppressed by telemetry.logging's content filter;
        # this counter is the operator's signal that nio is silently
        # losing typed dispatch on something. Keyed by event `type`
        # string when available, "<unknown>" otherwise.
        self._badevent_count: int = 0
        self._badevent_by_type: dict[str, int] = {}

    def _resolve_device_store_path(self, entry: IdentityFileEntry) -> Path:
        """Resolve the on-disk device store path for this identity.

        Operator override via `matrix_device_store_path` wins. Otherwise
        defaults to `<data_dir>/matrix/<identity_name>/store/`.
        """
        if entry.matrix_device_store_path:
            return Path(entry.matrix_device_store_path)
        return cast("Path", self._storage.data_dir) / "matrix" / entry.name / "store"

    def _build_client(self, entry: IdentityFileEntry) -> AsyncClient:
        """Construct the AsyncClient with E2EE config and persistent store."""
        homeserver = cast("str", entry.matrix_homeserver_url)
        user_id = cast("str", entry.matrix_user_id)
        access_token = cast("str", entry.matrix_access_token)
        device_id = entry.matrix_device_id

        self._device_store_path = self._resolve_device_store_path(entry)
        self._device_store_path.mkdir(parents=True, exist_ok=True)

        client_config = AsyncClientConfig(
            store_sync_tokens=True,
            encryption_enabled=True,
        )
        client = AsyncClient(
            homeserver,
            user_id,
            device_id=device_id,
            store_path=str(self._device_store_path),
            config=client_config,
        )
        client.access_token = access_token
        client.user_id = user_id
        if device_id is not None:
            client.device_id = device_id
        return client

    async def _load_device_store(self, entry: IdentityFileEntry) -> None:
        """Best-effort load of the persistent device store."""
        if self._client is None:
            return
        load_store = getattr(self._client, "load_store", None)
        if not callable(load_store):
            return
        try:
            result = load_store()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            _log.warning(
                "collector.matrix_store_load_failed",
                identity=entry.name,
                error=str(exc),
            )

    def _register_callbacks(self) -> None:
        """Register every event callback we care about."""
        if self._client is None:
            return
        self._client.add_event_callback(self._on_message, RoomMessageText)
        self._client.add_event_callback(self._on_media, RoomMessageImage)
        self._client.add_event_callback(self._on_media, RoomMessageFile)
        self._client.add_event_callback(self._on_media, RoomMessageVideo)
        self._client.add_event_callback(self._on_media, RoomMessageAudio)
        self._client.add_event_callback(self._on_reaction, ReactionEvent)
        self._client.add_event_callback(self._on_megolm, MegolmEvent)
        self._client.add_event_callback(self._on_badevent, BadEvent)
        self._client.add_event_callback(self._on_badevent, UnknownBadEvent)

    async def on_subscribe(self) -> None:
        await super().on_subscribe()
        entry = cast("IdentityFileEntry", self._claimed)

        missing = _missing_matrix_fields(entry)
        if missing:
            raise ValueError(
                f"identity {entry.name!r} missing required Matrix fields in "
                f"identities.toml: {', '.join(missing)}"
            )

        homeserver = cast("str", entry.matrix_homeserver_url)
        user_id = cast("str", entry.matrix_user_id)

        self._client = self._build_client(entry)
        await self._load_device_store(entry)
        await self._verify_auth(expected_user_id=user_id, homeserver=homeserver)

        for room in entry.matrix_monitor_rooms:
            resolved = await self._resolve_room(room)
            if resolved is not None:
                self._monitor_room_ids.add(resolved)

        self._source_uuid = await self._storage.upsert_source(
            kind=SourceKind.MATRIX,
            display_name=f"matrix:{entry.name}",
            created_at=datetime.now(tz=UTC),
        )

        async def _on_panic(_subject: str, _payload: bytes, _headers: dict[str, str]) -> None:
            _log.warning("collector.panic_received", identity=self._identity_name)
            await self._pool.freeze_all()
            await self.shutdown()

        await self._bus.subscribe("eyenet.control.global.panic", _on_panic)
        self._register_callbacks()

        _log.info(
            "collector.ready",
            identity=entry.name,
            instance_id=self.instance_id,
            monitor_rooms=sorted(self._monitor_room_ids) if self._monitor_room_ids else "all",
            backfill=self._backfill,
            device_store=str(self._device_store_path),
        )

        if self._backfill:
            if not self._monitor_room_ids:
                raise ValueError(
                    "--backfill requires matrix_monitor_rooms to be non-empty; "
                    "refusing to backfill every joined room."
                )
            self._backfill_task = asyncio.create_task(
                self._run_backfill(),
                name=f"matrix-backfill-{self.instance_id}",
            )

        self._sync_task = asyncio.create_task(
            self._client.sync_forever(
                timeout=_SYNC_TIMEOUT_MS,
                set_presence=_PRESENCE_OFFLINE,
            ),
            name=f"matrix-sync-{self.instance_id}",
        )

    async def _verify_auth(self, *, expected_user_id: str, homeserver: str) -> None:
        if self._client is None:
            raise RuntimeError("_verify_auth called before client init")
        try:
            resp = await self._client.whoami()
        except Exception as exc:
            raise ValueError(
                f"matrix_homeserver_url={homeserver!r} did not respond to "
                f"GET /account/whoami: {exc}. Check the URL — the API host is "
                "often different from the Element web URL (see .well-known/matrix/client)."
            ) from exc
        if isinstance(resp, WhoamiError):
            raise ValueError(
                f"matrix_access_token rejected by {homeserver}: "
                f"{resp.status_code} {resp.message}. The token may be expired or revoked."
            )
        if not isinstance(resp, WhoamiResponse):
            raise ValueError(
                f"unexpected whoami response from {homeserver}: {type(resp).__name__}. "
                "Likely the homeserver URL is wrong (Element web URL vs API host)."
            )
        if resp.user_id != expected_user_id:
            raise ValueError(
                f"matrix_user_id={expected_user_id!r} does not match the token's "
                f"actual user_id={resp.user_id!r}. Wrong token for this identity."
            )
        _log.info("collector.auth_verified", user_id=resp.user_id, homeserver=homeserver)

    async def _run_backfill(self) -> None:
        if self._client is None:
            raise RuntimeError("_run_backfill called before client init")
        sync_resp = await self._client.sync(timeout=_INITIAL_SYNC_TIMEOUT_MS)
        if not isinstance(sync_resp, SyncResponse):
            _log.error(
                "collector.backfill_initial_sync_failed",
                detail=type(sync_resp).__name__,
            )
            return

        for room_id in sorted(self._monitor_room_ids):
            room = self._client.rooms.get(room_id)
            if room is None:
                _log.warning(
                    "collector.backfill_skipped_unjoined",
                    room_id=room_id,
                    hint="identity is not joined to this room",
                )
                continue
            start_token = sync_resp.rooms.join.get(room_id, None)
            prev_batch = getattr(start_token.timeline, "prev_batch", None) if start_token else None
            if not prev_batch:
                _log.warning(
                    "collector.backfill_no_prev_batch",
                    room_id=room_id,
                    hint="no historical events visible via the initial sync",
                )
                continue
            await self._backfill_room(room, prev_batch, self._backfill_limit)

    async def _backfill_room(
        self,
        room: MatrixRoom,
        start_token: str,
        limit: int,
    ) -> None:
        if self._client is None:
            raise RuntimeError("_backfill_room called before client init")
        _log.info("collector.backfill_start", room_id=room.room_id, limit=limit)
        ingested = 0
        token: str | None = start_token
        while token is not None and ingested < limit:
            page_size = min(_BACKFILL_PAGE_SIZE, limit - ingested)
            resp = await self._client.room_messages(
                room.room_id,
                start=token,
                direction=MessageDirection.back,
                limit=page_size,
            )
            if isinstance(resp, RoomMessagesError):
                _log.error(
                    "collector.backfill_page_error",
                    room_id=room.room_id,
                    status=resp.status_code,
                    message=resp.message,
                )
                return
            if not isinstance(resp, RoomMessagesResponse):
                _log.error(
                    "collector.backfill_unexpected_response",
                    room_id=room.room_id,
                    detail=type(resp).__name__,
                )
                return
            if not resp.chunk:
                break
            for event in resp.chunk:
                if isinstance(event, RoomMessageText):
                    try:
                        await self._dispatch_text(room, event)
                        ingested += 1
                    except Exception as exc:
                        _log.error(
                            "collector.backfill_ingest_error",
                            error=str(exc),
                            room_id=room.room_id,
                            event_id=getattr(event, "event_id", None),
                        )
            if resp.end is None or resp.end == token:
                break
            token = resp.end
        _log.info(
            "collector.backfill_done",
            room_id=room.room_id,
            ingested=ingested,
            exhausted=(token is None),
        )

    async def _resolve_room(self, room: str) -> str | None:
        if self._client is None:
            raise RuntimeError("_resolve_room called before client init")
        if room.startswith("!"):
            return room
        if room.startswith("#"):
            resp = await self._client.room_resolve_alias(room)
            if isinstance(resp, RoomResolveAliasResponse):
                room_id: str = resp.room_id
                _log.info("collector.room_resolved", alias=room, room_id=room_id)
                return room_id
            if isinstance(resp, RoomResolveAliasError):
                _log.warning("collector.room_resolve_failed", alias=room, error=resp.message)
                return None
        _log.warning(
            "collector.room_unrecognized_form",
            room=room,
            hint="expected '!room_id:server' or '#alias:server'",
        )
        return None

    # ---- event callbacks --------------------------------------------------

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        try:
            await self._dispatch_text(room, event)
        except Exception as exc:
            _log.error(
                "collector.ingest_error",
                error=str(exc),
                room_id=room.room_id,
                event_id=getattr(event, "event_id", None),
            )

    async def _on_media(self, room: MatrixRoom, event: Any) -> None:
        try:
            await self._ingest_media_event(room, event)
        except Exception as exc:
            _log.error(
                "collector.media_ingest_error",
                error=str(exc),
                room_id=room.room_id,
                event_id=getattr(event, "event_id", None),
            )

    async def _on_reaction(self, room: MatrixRoom, event: ReactionEvent) -> None:
        try:
            await self._ingest_reaction_event(room, event)
        except Exception as exc:
            _log.error(
                "collector.reaction_ingest_error",
                error=str(exc),
                room_id=room.room_id,
                event_id=getattr(event, "event_id", None),
            )

    async def _on_badevent(self, room: MatrixRoom, event: BadEvent | UnknownBadEvent) -> None:
        """Observe an event nio could not type-validate.

        nio still delivered it (as `BadEvent` / `UnknownBadEvent`) and the
        room continues to receive sync updates — only typed dispatch was
        lost. We count + log structurally so the operator has evidence
        that the stderr filter on `nio.events.misc` isn't masking real
        message loss.
        """
        ev_type = getattr(event, "type", None) or "<unknown>"
        self._badevent_count += 1
        self._badevent_by_type[ev_type] = self._badevent_by_type.get(ev_type, 0) + 1
        _log.warning(
            "collector.matrix_badevent",
            room_id=getattr(room, "room_id", None),
            event_type=ev_type,
            event_id=getattr(event, "event_id", None),
            sender=getattr(event, "sender", None),
            total=self._badevent_count,
            type_total=self._badevent_by_type[ev_type],
        )

    async def _on_megolm(self, room: MatrixRoom, event: MegolmEvent) -> None:
        if self._client is None:
            return
        try:
            decrypted = self._client.decrypt_event(event)
        except Exception as exc:
            # Missing inbound group session, expired session, or no libolm.
            _log.warning(
                "collector.megolm_decrypt_failed",
                room_id=room.room_id,
                event_id=getattr(event, "event_id", None),
                error=str(exc),
            )
            await self._emit_decrypt_sentinel(room, event, reason=str(exc))
            return
        if decrypted is None or isinstance(decrypted, MegolmEvent):
            await self._emit_decrypt_sentinel(room, event, reason="no key")
            return
        # Dispatch the decrypted event through the appropriate handler.
        if isinstance(decrypted, RoomMessageText):
            await self._dispatch_text(room, decrypted)
        elif isinstance(
            decrypted, (RoomMessageImage, RoomMessageFile, RoomMessageVideo, RoomMessageAudio)
        ):
            await self._ingest_media_event(room, decrypted)
        elif isinstance(decrypted, ReactionEvent):
            await self._ingest_reaction_event(room, decrypted)

    # ---- dispatch helpers -------------------------------------------------

    def _should_ingest(self, room: MatrixRoom, sender: str | None) -> bool:
        if self._monitor_room_ids and room.room_id not in self._monitor_room_ids:
            return False
        return not (
            self._client is not None and sender is not None and sender == self._client.user_id
        )

    @staticmethod
    def _extract_relation(event: Any) -> dict[str, Any]:
        """Return the `m.relates_to` dict from an event's raw source, or {}."""
        source = getattr(event, "source", None) or {}
        content = source.get("content", {}) if isinstance(source, dict) else {}
        relates_to = content.get("m.relates_to", {}) if isinstance(content, dict) else {}
        return relates_to if isinstance(relates_to, dict) else {}

    @classmethod
    def _extract_reply_to(cls, event: Any) -> str | None:
        relates_to = cls._extract_relation(event)
        in_reply_to = relates_to.get("m.in_reply_to", {})
        if isinstance(in_reply_to, dict):
            event_id = in_reply_to.get("event_id")
            if isinstance(event_id, str) and event_id:
                return event_id
        return None

    @classmethod
    def _is_edit(cls, event: Any) -> tuple[bool, str | None, str | None]:
        """Return (is_edit, target_event_id, new_body) for `m.replace` events."""
        relates_to = cls._extract_relation(event)
        if relates_to.get("rel_type") != "m.replace":
            return False, None, None
        target = relates_to.get("event_id")
        source = getattr(event, "source", None) or {}
        content = source.get("content", {}) if isinstance(source, dict) else {}
        new_content = content.get("m.new_content", {}) if isinstance(content, dict) else {}
        new_body = new_content.get("body") if isinstance(new_content, dict) else None
        if not isinstance(target, str) or not isinstance(new_body, str):
            return False, None, None
        return True, target, new_body

    # ---- text + edit ingestion --------------------------------------------

    async def _dispatch_text(self, room: MatrixRoom, event: RoomMessageText) -> None:
        is_edit, target_id, new_body = self._is_edit(event)
        if is_edit and target_id is not None and new_body is not None:
            await self._ingest_edit(room, event, target_id, new_body)
            return
        await self._ingest_event(room, event)

    async def _ingest_edit(
        self,
        room: MatrixRoom,
        event: RoomMessageText,
        target_event_id: str,
        new_body: str,
    ) -> None:
        """Apply an `m.replace` edit to the target message.

        Operator-grade evidence: ALL prior versions are preserved in
        `source_specific.edits`. The top-level `body` becomes the latest
        edit; the original is recorded as the first entry.
        """
        if not self._should_ingest(room, event.sender):
            return
        if self._source_uuid is None:
            raise RuntimeError("source_uuid not set — on_subscribe incomplete")

        edited_at = datetime.fromtimestamp(event.server_timestamp / 1000.0, tz=UTC)
        async with self._storage.session() as session:
            group = await self._lookup_group_uuid(session, room.room_id)
            if group is None:
                _log.warning(
                    "collector.edit_target_room_unknown",
                    room_id=room.room_id,
                    target_event_id=target_event_id,
                )
                return
            target_uuid = await self._storage.resolve_message_id(
                source_id=self._source_uuid,
                group_id=group,
                platform_msgid=target_event_id,
            )
            if target_uuid is None:
                _log.warning(
                    "collector.edit_target_unknown",
                    room_id=room.room_id,
                    target_event_id=target_event_id,
                )
                return
            target = await session.get(MessageTable, target_uuid)
            if target is None:
                return
            edits = list(target.source_specific.get("edits", []))
            if not edits:
                edits.append(
                    {
                        "event_id": target.platform_msgid,
                        "body": target.body,
                        "edited_at": target.sent_at_source.isoformat(),
                    }
                )
            edits.append(
                {
                    "event_id": event.event_id,
                    "body": new_body,
                    "edited_at": edited_at.isoformat(),
                }
            )
            target.source_specific = {**target.source_specific, "edits": edits}
            target.body = new_body
            target.length_chars = len(new_body)
            target.length_words = len(new_body.split())
            session.add(target)
            await session.commit()

        _log.info(
            "collector.edit_applied",
            room_id=room.room_id,
            target_event_id=target_event_id,
            edit_event_id=event.event_id,
        )

    async def _lookup_group_uuid(self, session: Any, platform_groupid: str) -> UUID | None:
        result = await session.exec(
            select(GroupTable.id).where(
                GroupTable.source_id == self._source_uuid,
                GroupTable.platform_groupid == platform_groupid,
            )
        )
        row = result.first()
        if row is None:
            return None
        return UUID(str(row))

    async def _ingest_event(self, room: MatrixRoom, event: RoomMessageText) -> None:
        with _tracer.start_as_current_span(
            "collector.ingest",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "source.platform": "matrix",
                "source.id": str(self._source_uuid) if self._source_uuid else "",
                "message.kind": "text",
                "message.platform_msgid": str(getattr(event, "event_id", "")),
                "message.platform_groupid": str(room.room_id),
            },
        ):
            await self._ingest_event_inner(room, event)

    async def _ingest_event_inner(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if not self._should_ingest(room, event.sender):
            return
        body = event.body or ""
        if not body:
            return

        sent_at = datetime.fromtimestamp(event.server_timestamp / 1000.0, tz=UTC)
        collected_at = datetime.now(tz=UTC)

        actor_key = "actor:" + hashlib.sha256(f"matrix||{event.sender}".encode()).hexdigest()
        platform_groupid = room.room_id
        platform_msgid = event.event_id
        group_title = room.display_name or room.machine_name or None
        group_kind = GroupKind.MATRIX_ROOM

        if self._source_uuid is None:
            raise RuntimeError("source_uuid not set — on_subscribe incomplete")

        display_name = room.user_name(event.sender) or None
        reply_to_platform_msgid = self._extract_reply_to(event)

        group_id = await self._storage.upsert_group(
            source_id=self._source_uuid,
            platform_groupid=platform_groupid,
            kind=group_kind,
            title=group_title,
            seen_at=collected_at,
        )
        actor_id = await self._storage.upsert_actor(
            source_id=self._source_uuid,
            actor_key=actor_key,
            platform_userid=event.sender,
            handle=event.sender,
            display_name=display_name,
            seen_at=sent_at,
        )
        reply_to_msg_id: UUID | None = None
        source_specific: dict[str, Any] = {}
        if reply_to_platform_msgid is not None:
            reply_to_msg_id = await self._storage.resolve_message_id(
                source_id=self._source_uuid,
                group_id=group_id,
                platform_msgid=reply_to_platform_msgid,
            )
            if reply_to_msg_id is None:
                source_specific["pending_reply_to"] = reply_to_platform_msgid

        evidence_ref = f"matrix:{platform_groupid}:{platform_msgid}"
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()

        source_uuid: UUID = self._source_uuid
        msg_row = MessageTable(
            id=new_uuid7(),
            source_id=source_uuid,
            group_id=group_id,
            actor_id=actor_id,
            platform_msgid=platform_msgid,
            evidence_ref=evidence_ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=sent_at,
            ingested_at=collected_at,
            has_attachment=False,
            reply_to_msg_id=reply_to_msg_id,
            forward_of_msg_id=None,
            source_specific=source_specific,
        )

        written = await self._storage.put_message(msg_row, [])

        traceparent = current_traceparent() or _zero_traceparent()
        env = RawMessageEnvelope(
            source=SourceKind.MATRIX,
            instance_id=self.instance_id,
            evidence_ref=evidence_ref,
            actor_key=actor_key,
            platform_groupid=platform_groupid,
            platform_msgid=platform_msgid,
            sent_at_source=sent_at,
            collected_at=collected_at,
            length_chars=len(body),
            length_words=len(body.split()),
            body_sha256=body_sha256,
            is_forward=False,
            has_attachment=False,
            reply_to_platform_msgid=reply_to_platform_msgid,
            trace_context=TraceContext(traceparent=traceparent),
        )

        await self.publisher.publish(
            subject_for(SourceKind.MATRIX, self.instance_id),
            env,
        )
        if written:
            self._record_emission()
            self._recent.append(_time.monotonic())
            _log.info(
                "collector.ingested",
                evidence_ref=evidence_ref,
                words=len(body.split()),
                actor_key=actor_key[:16],
            )

    # ---- attachments ------------------------------------------------------

    @staticmethod
    def _attachment_kind_for_event(event: Any) -> AttachmentKind:
        """Map a media event to AttachmentKind, with voice-note detection."""
        source = getattr(event, "source", None) or {}
        content = source.get("content", {}) if isinstance(source, dict) else {}
        if isinstance(content, dict):
            if "org.matrix.msc3245.voice" in content:
                return AttachmentKind.VOICE
            kind = _MSGTYPE_KIND.get(content.get("msgtype", ""))
            if kind is not None:
                return kind
        for cls, fallback in _MEDIA_MSGTYPE_KIND.items():
            if isinstance(event, cls):
                return fallback
        return AttachmentKind.OTHER

    @staticmethod
    def _parse_mxc(mxc_uri: str) -> tuple[str, str] | None:
        """`mxc://server/mediaid` -> `(server, media_id)`."""
        if not mxc_uri.startswith("mxc://"):
            return None
        rest = mxc_uri[6:]
        if "/" not in rest:
            return None
        server, media_id = rest.split("/", 1)
        if not server or not media_id:
            return None
        return server, media_id

    @staticmethod
    def _extract_media_descriptor(event: Any) -> dict[str, Any]:
        """Return the relevant fields from a media event's content.

        For unencrypted media: `{"url": mxc, ...}`.
        For encrypted media: `{"file": {"url": mxc, "key": ..., "iv": ..., "hashes": ...}}`.
        We return a normalized dict with: `mxc`, `key` (None if cleartext),
        `iv`, `hashes`, `mime`, `size`, `filename`.
        """
        source = getattr(event, "source", None) or {}
        content = source.get("content", {}) if isinstance(source, dict) else {}
        info = content.get("info", {}) if isinstance(content, dict) else {}
        file_block = content.get("file") if isinstance(content, dict) else None

        if isinstance(file_block, dict) and "url" in file_block:
            return {
                "mxc": file_block.get("url"),
                "key": file_block.get("key"),
                "iv": file_block.get("iv"),
                "hashes": file_block.get("hashes", {}),
                "mime": info.get("mimetype") if isinstance(info, dict) else None,
                "size": info.get("size") if isinstance(info, dict) else None,
                "filename": content.get("body") if isinstance(content, dict) else None,
            }
        return {
            "mxc": content.get("url") if isinstance(content, dict) else None,
            "key": None,
            "iv": None,
            "hashes": {},
            "mime": info.get("mimetype") if isinstance(info, dict) else None,
            "size": info.get("size") if isinstance(info, dict) else None,
            "filename": content.get("body") if isinstance(content, dict) else None,
        }

    @staticmethod
    def _decrypt_and_verify(
        ciphertext: bytes,
        descriptor: dict[str, Any],
        mxc: str,
    ) -> tuple[bytes | None, bool]:
        """Decrypt a Matrix encrypted attachment and verify its sha256."""
        key = descriptor["key"]
        iv = descriptor.get("iv") or ""
        hashes = descriptor.get("hashes", {})
        announced = hashes.get("sha256") if isinstance(hashes, dict) else None
        try:
            plain = decrypt_attachment(ciphertext, key.get("k", ""), hashes, iv)
        except Exception as exc:
            _log.warning("collector.attachment_decrypt_failed", mxc=mxc, error=str(exc))
            return None, False
        if announced is None:
            return plain, True
        actual_digest = hashlib.sha256(plain).digest()
        actual = base64.b64encode(actual_digest).decode("ascii").rstrip("=")
        if actual != announced.rstrip("="):
            _log.warning(
                "collector.attachment_integrity_mismatch",
                mxc=mxc,
                announced=announced,
            )
            return plain, False
        return plain, True

    async def _download_media(self, descriptor: dict[str, Any]) -> tuple[bytes | None, bool]:
        """Download (and decrypt if needed) the bytes referenced by `descriptor`.

        Returns `(payload_or_none, integrity_ok)`. integrity_ok is False
        when an encrypted attachment fails its announced sha256 check.
        """
        if self._client is None:
            return None, False
        mxc = descriptor.get("mxc")
        if not isinstance(mxc, str):
            return None, False
        parsed = self._parse_mxc(mxc)
        if parsed is None:
            return None, False
        server, media_id = parsed
        resp = await self._client.download(server, media_id)
        body: bytes | None = getattr(resp, "body", None)
        if body is None:
            return None, False
        if isinstance(descriptor.get("key"), dict):
            return self._decrypt_and_verify(body, descriptor, mxc)
        return body, True

    async def _ingest_media_event(self, room: MatrixRoom, event: Any) -> None:
        with _tracer.start_as_current_span(
            "collector.ingest",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "source.platform": "matrix",
                "source.id": str(self._source_uuid) if self._source_uuid else "",
                "message.kind": "media",
                "message.platform_msgid": str(getattr(event, "event_id", "")),
                "message.platform_groupid": str(room.room_id),
            },
        ):
            await self._ingest_media_event_inner(room, event)

    async def _ingest_media_event_inner(self, room: MatrixRoom, event: Any) -> None:
        if not self._should_ingest(room, getattr(event, "sender", None)):
            return
        if self._source_uuid is None:
            raise RuntimeError("source_uuid not set — on_subscribe incomplete")

        descriptor = self._extract_media_descriptor(event)
        payload, integrity_ok = await self._download_media(descriptor)

        sent_at = datetime.fromtimestamp(event.server_timestamp / 1000.0, tz=UTC)
        collected_at = datetime.now(tz=UTC)
        actor_key = "actor:" + hashlib.sha256(f"matrix||{event.sender}".encode()).hexdigest()
        platform_groupid = room.room_id
        platform_msgid = event.event_id
        group_title = room.display_name or room.machine_name or None
        body = getattr(event, "body", "") or ""

        display_name = room.user_name(event.sender) or None
        reply_to_platform_msgid = self._extract_reply_to(event)

        group_id = await self._storage.upsert_group(
            source_id=self._source_uuid,
            platform_groupid=platform_groupid,
            kind=GroupKind.MATRIX_ROOM,
            title=group_title,
            seen_at=collected_at,
        )
        actor_id = await self._storage.upsert_actor(
            source_id=self._source_uuid,
            actor_key=actor_key,
            platform_userid=event.sender,
            handle=event.sender,
            display_name=display_name,
            seen_at=sent_at,
        )
        reply_to_msg_id: UUID | None = None
        source_specific: dict[str, Any] = {}
        if reply_to_platform_msgid is not None:
            reply_to_msg_id = await self._storage.resolve_message_id(
                source_id=self._source_uuid,
                group_id=group_id,
                platform_msgid=reply_to_platform_msgid,
            )
            if reply_to_msg_id is None:
                source_specific["pending_reply_to"] = reply_to_platform_msgid

        sha256: str | None = None
        storage_uri: str | None = None
        if payload is not None and integrity_ok:
            sha256, storage_uri = store_attachment(
                self._storage.data_dir,
                payload,
                source=SourceKind.MATRIX,
                instance_id=self.instance_id,
            )
        elif payload is not None and not integrity_ok:
            source_specific["attachment_integrity_failed"] = True

        evidence_ref = f"matrix:{platform_groupid}:{platform_msgid}"
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        source_uuid: UUID = self._source_uuid

        msg_row = MessageTable(
            id=new_uuid7(),
            source_id=source_uuid,
            group_id=group_id,
            actor_id=actor_id,
            platform_msgid=platform_msgid,
            evidence_ref=evidence_ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=sent_at,
            ingested_at=collected_at,
            has_attachment=True,
            reply_to_msg_id=reply_to_msg_id,
            forward_of_msg_id=None,
            source_specific=source_specific,
        )

        kind = self._attachment_kind_for_event(event)
        mime = descriptor.get("mime") or "application/octet-stream"
        size = descriptor.get("size") or (len(payload) if payload else 0)
        filename = descriptor.get("filename")

        # Born provisional CLASSIFIED when we have bytes on disk — the
        # ClassifierService settles the real tier off-path (§0 fail-closed).
        # No bytes (integrity-failed / undownloaded) → nothing to classify.
        provisional_tier = (
            SensitivityTier.CLASSIFIED if storage_uri is not None else SensitivityTier.NORMAL
        )
        attachment_row = AttachmentTable(
            id=new_uuid7(),
            message_id=msg_row.id,
            kind=kind,
            mime=str(mime),
            size_bytes=int(size) if isinstance(size, int) else 0,
            sha256=sha256 or ("0" * 64),
            filename=filename if isinstance(filename, str) else None,
            storage_uri=storage_uri,
            classifier_tier=provisional_tier,
        )

        written = await self._storage.put_message(msg_row, [attachment_row])

        traceparent = current_traceparent() or _zero_traceparent()
        env = RawMessageEnvelope(
            source=SourceKind.MATRIX,
            instance_id=self.instance_id,
            evidence_ref=evidence_ref,
            actor_key=actor_key,
            platform_groupid=platform_groupid,
            platform_msgid=platform_msgid,
            sent_at_source=sent_at,
            collected_at=collected_at,
            length_chars=len(body),
            length_words=len(body.split()),
            body_sha256=body_sha256,
            is_forward=False,
            has_attachment=True,
            reply_to_platform_msgid=reply_to_platform_msgid,
            trace_context=TraceContext(traceparent=traceparent),
        )
        await self.publisher.publish(
            subject_for(SourceKind.MATRIX, self.instance_id),
            env,
        )
        if written:
            self._record_emission()
            self._recent.append(_time.monotonic())
            _log.info(
                "collector.attachment_ingested",
                evidence_ref=evidence_ref,
                kind=kind.value,
                size=attachment_row.size_bytes,
                sha256=attachment_row.sha256[:16],
            )
            # Trigger async classification only when bytes are on disk to read.
            if storage_uri is not None and sha256 is not None:
                await self.publisher.publish(
                    SUBJECT_ATTACHMENT_STORED,
                    AttachmentStoredEnvelope(
                        attachment_id=attachment_row.id,
                        message_id=msg_row.id,
                        storage_uri=storage_uri,
                        sha256=sha256,
                        mime=str(mime),
                        trace_context=TraceContext(traceparent=traceparent),
                    ),
                )

    # ---- reactions --------------------------------------------------------

    async def _ingest_reaction_event(self, room: MatrixRoom, event: ReactionEvent) -> None:
        if not self._should_ingest(room, getattr(event, "sender", None)):
            return
        if self._source_uuid is None:
            raise RuntimeError("source_uuid not set — on_subscribe incomplete")

        relates_to = self._extract_relation(event)
        target_event_id = relates_to.get("event_id")
        emoji = relates_to.get("key")
        if not isinstance(target_event_id, str) or not isinstance(emoji, str):
            _log.warning(
                "collector.reaction_malformed",
                room_id=room.room_id,
                event_id=getattr(event, "event_id", None),
            )
            return

        reacted_at = datetime.fromtimestamp(event.server_timestamp / 1000.0, tz=UTC)
        actor_key = "actor:" + hashlib.sha256(f"matrix||{event.sender}".encode()).hexdigest()
        evidence_ref = f"matrix:{room.room_id}:{event.event_id}"

        async with self._storage.session() as lookup_session:
            group_uuid = await self._lookup_group_uuid(lookup_session, room.room_id)
        if group_uuid is None:
            _log.warning(
                "collector.reaction_target_room_unknown",
                room_id=room.room_id,
                target=target_event_id,
            )
            return
        target_uuid = await self._storage.resolve_message_id(
            source_id=self._source_uuid,
            group_id=group_uuid,
            platform_msgid=target_event_id,
        )
        if target_uuid is None:
            _log.warning(
                "collector.reaction_target_unknown",
                room_id=room.room_id,
                target=target_event_id,
            )
            return
        actor_id = await self._storage.upsert_actor(
            source_id=self._source_uuid,
            actor_key=actor_key,
            platform_userid=event.sender,
            handle=event.sender,
            display_name=room.user_name(event.sender) or None,
            seen_at=reacted_at,
        )
        row = ReactionTable(
            id=new_uuid7(),
            message_id=target_uuid,
            actor_id=actor_id,
            emoji=emoji,
            reacted_at=reacted_at,
            evidence_ref=evidence_ref,
        )
        async with self._storage.session() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                # Unique evidence_ref collision -> idempotent re-delivery.
                await session.rollback()
                return

        _log.info(
            "collector.reaction_ingested",
            evidence_ref=evidence_ref,
            emoji=emoji,
            target=target_event_id,
        )

    # ---- decrypt sentinel -------------------------------------------------

    async def _emit_decrypt_sentinel(
        self,
        room: MatrixRoom,
        event: MegolmEvent,
        reason: str,
    ) -> None:
        with _tracer.start_as_current_span(
            "collector.ingest",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "source.platform": "matrix",
                "source.id": str(self._source_uuid) if self._source_uuid else "",
                "message.kind": "decrypt_sentinel",
                "message.platform_msgid": str(getattr(event, "event_id", "")),
                "message.platform_groupid": str(room.room_id),
                "decrypt.failure_reason": reason,
            },
        ):
            await self._emit_decrypt_sentinel_inner(room, event, reason)

    async def _emit_decrypt_sentinel_inner(
        self,
        room: MatrixRoom,
        event: MegolmEvent,
        reason: str,
    ) -> None:
        """Emit a placeholder envelope so undecryptable events are counted.

        Operator-grade evidence: we do NOT silently drop a Megolm event we
        can't decrypt. The envelope carries an empty body but preserves
        the event_id, sender, and timestamp, plus a flag in source_specific.
        """
        if not self._should_ingest(room, getattr(event, "sender", None)):
            return
        if self._source_uuid is None:
            return
        sent_at = datetime.fromtimestamp(event.server_timestamp / 1000.0, tz=UTC)
        collected_at = datetime.now(tz=UTC)
        actor_key = "actor:" + hashlib.sha256(f"matrix||{event.sender}".encode()).hexdigest()
        evidence_ref = f"matrix:{room.room_id}:{event.event_id}"
        body_sha256 = hashlib.sha256(b"").hexdigest()

        traceparent = current_traceparent() or _zero_traceparent()
        env = RawMessageEnvelope(
            source=SourceKind.MATRIX,
            instance_id=self.instance_id,
            evidence_ref=evidence_ref,
            actor_key=actor_key,
            platform_groupid=room.room_id,
            platform_msgid=event.event_id,
            sent_at_source=sent_at,
            collected_at=collected_at,
            length_chars=0,
            length_words=0,
            body_sha256=body_sha256,
            is_forward=False,
            has_attachment=False,
            reply_to_platform_msgid=None,
            trace_context=TraceContext(traceparent=traceparent),
        )
        await self.publisher.publish(
            subject_for(SourceKind.MATRIX, self.instance_id),
            env,
        )
        _log.warning(
            "collector.megolm_sentinel_emitted",
            evidence_ref=evidence_ref,
            reason=reason,
            session_id=getattr(event, "session_id", None),
        )

    # ---- lifecycle --------------------------------------------------------

    async def health(self) -> CollectorHealth:
        now = _time.monotonic()
        hour_ago = now - 3600
        msgs_last_hour = sum(1 for t in self._recent if t >= hour_ago)

        subs: list[str] = []
        if self._client is not None:
            for room_id in sorted(self._client.rooms.keys()):
                subs.append(room_id)
                if len(subs) >= _HEALTH_SUBS_CAP:
                    break

        state = (
            CollectorState.RUNNING
            if (self._sync_task is not None and not self._sync_task.done())
            else CollectorState.STARTING
        )

        return CollectorHealth(
            state=state,
            identity_name=self._identity_name,
            instance_id=self.instance_id,
            last_message_at=self._last_message_at,
            messages_in_last_hour=msgs_last_hour,
            current_subscriptions=subs,
        )

    async def shutdown(self) -> None:
        if self._backfill_task is not None:
            self._backfill_task.cancel()
            try:
                await self._backfill_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                _log.warning(
                    "collector.backfill_task_shutdown_error",
                    identity=self._identity_name,
                    error=str(exc),
                )
            self._backfill_task = None
        if self._sync_task is not None:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                _log.warning(
                    "collector.sync_task_shutdown_error",
                    identity=self._identity_name,
                    error=str(exc),
                )
            self._sync_task = None
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:
                _log.warning(
                    "collector.client_close_failed",
                    identity=self._identity_name,
                    error=str(exc),
                )
            self._client = None
        if self._claimed:
            try:
                await self._pool.release(self._identity_name, new_state=IdentityState.AVAILABLE)
            except Exception as exc:
                _log.warning(
                    "collector.pool_release_failed",
                    identity=self._identity_name,
                    error=str(exc),
                )
        await super().shutdown()


# --- helpers ---


def _missing_matrix_fields(entry: IdentityFileEntry) -> list[str]:
    """Return the names of required Matrix fields that are unset."""
    missing: list[str] = []
    if not entry.matrix_homeserver_url:
        missing.append("matrix_homeserver_url")
    if not entry.matrix_user_id:
        missing.append("matrix_user_id")
    if not entry.matrix_access_token:
        missing.append("matrix_access_token")
    return missing


__all__ = ["MatrixCollector"]
