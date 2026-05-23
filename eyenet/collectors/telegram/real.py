"""`TelegramCollector` — real telethon-based message collector.

One process = one identity = all dialogs that identity is joined to.
Per PLAN §2.1 scoping rule: we do NOT spawn per-channel processes; one
collector multiplexes all dialogs onto the bus.

Identity claim: `FileIdentityPool.claim()` locks the identity for the
session duration. On `shutdown()`, we disconnect the client and release.

OPSEC: session file is per-identity; proxy/Tor circuit pulled from pool
config. Panic (`eyenet.control.global.panic`) freezes the pool fleet-wide.
"""

from __future__ import annotations

import asyncio
import hashlib
import time as _time
from collections import deque
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import structlog
from sqlmodel import Session
from telethon import TelegramClient, events
from telethon.tl.types import (
    Channel,
    Chat,
    Document,
    Message as TLMessage,
    MessageMediaDocument,
    MessageMediaPhoto,
    Photo,
    User,
)

from eyenet.collectors.base.skeleton import CollectorSkeleton
from eyenet.contracts._base import TraceContext
from eyenet.contracts.bus import Bus
from eyenet.contracts.collector import CollectorHealth
from eyenet.contracts.enums import (
    AttachmentKind,
    CollectorState,
    GroupKind,
    IdentityState,
    SourceKind,
)
from eyenet.contracts.identity_pool import IdentityPool
from eyenet.contracts.raw_message import RawMessageEnvelope, subject_for
from eyenet.identity_pool.loader import IdentityFileEntry
from eyenet.models import AttachmentTable, MessageTable
from eyenet.models._base import new_uuid7
from eyenet.storage import SQLiteStorage, upsert_actor, upsert_group, upsert_source
from eyenet.storage.engines import StoreName
from eyenet.storage.messages import SQLiteMessageStore
from eyenet.telemetry.propagation import current_traceparent

_log = structlog.get_logger()

# max subscriptions returned in health()
_HEALTH_SUBS_CAP = 100
# length of the "100" marked-peer prefix in stringified Telegram peer IDs
_MARKED_PEER_PREFIX_LEN = 3


def _zero_traceparent() -> str:
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


class TelegramCollector(CollectorSkeleton):
    """Telethon-based real Telegram collector."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: SQLiteStorage,
        pool: IdentityPool,
        identity_name: str,
        backfill: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name=identity_name,
            source_kind=SourceKind.TELEGRAM,
        )
        self._client: TelegramClient | None = None
        self._source_uuid: UUID | None = None
        # Raw positive entity IDs (Channel.id / Chat.id) — the only form
        # that's consistent across get_entity(), dialog.entity.id, and
        # abs(event.chat_id). dialog.id and event.chat_id use varying
        # negative forms depending on Telethon version.
        self._monitor_raw_ids: set[int] | None = None
        self._backfill = backfill
        self._recent: deque[float] = deque(maxlen=3600)

    @property
    def _msg_store(self) -> SQLiteMessageStore:
        return self._storage._messages

    async def on_subscribe(self) -> None:
        await super().on_subscribe()
        entry = cast("IdentityFileEntry", self._claimed)

        api_id = entry.telegram_api_id
        api_hash = entry.telegram_api_hash
        if api_id is None or api_hash is None:
            raise ValueError(
                f"identity {entry.name!r} missing telegram_api_id / telegram_api_hash "
                "in identities.toml"
            )

        proxy = _parse_proxy(entry.proxy_uri)

        self._client = TelegramClient(
            entry.session_path,
            api_id,
            api_hash,
            proxy=proxy,
        )
        await self._client.start()

        # Resolve monitor_groups to raw entity IDs (positive Channel.id / Chat.id).
        # We never use dialog.id or event.chat_id directly for matching because
        # Telethon's negative peer ID format differs between versions. Instead we
        # compare abs(_strip_100(event.chat_id)) == entity.id everywhere.
        if entry.monitor_groups:
            resolved: set[int] = set()
            for g in entry.monitor_groups:
                try:
                    resolved.add(_to_raw_entity_id(g))
                except ValueError:
                    # @username string — resolve via API
                    try:
                        entity = await self._client.get_entity(g)
                        resolved.add(entity.id)  # type: ignore[union-attr]
                        _log.info("collector.group_resolved", username=g, entity_id=entity.id)  # type: ignore[union-attr]
                    except Exception as exc:
                        _log.warning("collector.group_resolve_failed", group=g, error=str(exc))
            if resolved:
                self._monitor_raw_ids = resolved

        # Ensure a SourceTable row exists for this identity.
        messages_engine = self._storage._engines[StoreName.MESSAGES]
        with Session(messages_engine) as session:
            self._source_uuid = upsert_source(
                session,
                kind=SourceKind.TELEGRAM,
                display_name=f"telegram:{entry.name}",
                base_url="https://t.me",
                created_at=datetime.now(tz=UTC),
            )
            session.commit()

        # Subscribe to panic kill-switch (PLAN §6.2).
        async def _on_panic(_subject: str, _payload: bytes, _headers: dict[str, str]) -> None:
            _log.warning("collector.panic_received", identity=self._identity_name)
            await self._pool.freeze_all()
            await self.shutdown()

        await self._bus.subscribe("eyenet.control.global.panic", _on_panic)

        _log.info(
            "collector.ready",
            identity=entry.name,
            instance_id=self.instance_id,
            monitor_raw_ids=sorted(self._monitor_raw_ids) if self._monitor_raw_ids else "all",
            backfill=self._backfill,
        )

        # Register the Telethon event handler (no chats= filter — we filter in
        # _ingest_message to avoid Telethon's entity-resolution at startup).
        @self._client.on(events.NewMessage)  # type: ignore[untyped-decorator]
        async def _on_new_message(event: events.NewMessage.Event) -> None:
            try:
                await self._ingest_message(event)
            except Exception as exc:
                _log.error(
                    "collector.ingest_error",
                    error=str(exc),
                    chat_id=getattr(event, "chat_id", None),
                )

        if self._backfill:
            asyncio.create_task(self._run_backfill())  # noqa: RUF006

    async def _ingest_message(self, event: events.NewMessage.Event) -> None:
        """Live handler: filter, extract, delegate to _ingest_msg."""
        if (
            self._monitor_raw_ids is not None
            and _chat_raw_id(event.chat_id) not in self._monitor_raw_ids
        ):
            return
        msg = event.message
        if not msg or not msg.message:
            return
        sender = await event.get_sender()
        chat = await event.get_chat()
        await self._ingest_msg(msg, chat_id=event.chat_id, sender=sender, chat=chat)

    async def _run_backfill(self) -> None:
        """Replay historical messages oldest-first for each monitored group.

        Uses iter_dialogs to resolve proper InputPeer entities — passing raw
        integers to iter_messages is unreliable because Telethon's entity cache
        may not map bare IDs to the right peer type (Channel vs Chat).
        """
        if self._client is None:
            raise RuntimeError("backfill called before on_subscribe attached a client")
        if self._monitor_raw_ids is None:
            _log.warning(
                "collector.backfill_skipped", reason="monitor_groups required for backfill"
            )
            return

        found: set[int] = set()
        async for dialog in self._client.iter_dialogs():
            raw = getattr(dialog.entity, "id", None)
            if raw not in self._monitor_raw_ids:
                continue
            found.add(raw)
            entity = dialog.entity
            chat_id = dialog.id
            written = skipped = 0
            _log.info("collector.backfill_start", chat_id=chat_id, title=dialog.title)
            total = 0
            try:
                async for msg in self._client.iter_messages(entity, reverse=True, limit=None):
                    total += 1
                    if total % 500 == 0:
                        _log.info(
                            "collector.backfill_progress",
                            chat_id=chat_id,
                            seen=total,
                            written=written,
                        )
                    if not isinstance(msg, TLMessage) or not msg.message:
                        continue
                    ok = await self._ingest_msg(
                        msg,
                        chat_id=chat_id,
                        sender=getattr(msg, "sender", None),
                        chat=entity,
                    )
                    if ok:
                        written += 1
                    else:
                        skipped += 1
            except Exception as exc:
                _log.error("collector.backfill_error", chat_id=chat_id, error=str(exc))
            _log.info("collector.backfill_done", chat_id=chat_id, written=written, skipped=skipped)

        not_found = self._monitor_raw_ids - found
        if not_found:
            _log.warning(
                "collector.backfill_no_dialog",
                missing_ids=sorted(not_found),
                hint="identity may not be a member, or IDs are wrong format",
            )

    async def _ingest_msg(
        self,
        msg: TLMessage,
        *,
        chat_id: int,
        sender: object,
        chat: object,
    ) -> bool:
        """Core ingest: persist + publish one message. Returns True if written."""
        sent_at = msg.date.replace(tzinfo=UTC) if msg.date.tzinfo is None else msg.date
        collected_at = datetime.now(tz=UTC)

        # --- actor_key ---
        sender_id = msg.sender_id or 0
        actor_key = "actor:" + hashlib.sha256(f"telegram||{sender_id}".encode()).hexdigest()

        # --- sender metadata ---
        handle: str | None = None
        display_name: str | None = None
        if isinstance(sender, User):
            handle = f"@{sender.username}" if sender.username else None
            display_name = " ".join(filter(None, [sender.first_name, sender.last_name])) or None

        # --- chat metadata ---
        platform_groupid = str(chat_id)
        group_kind = _chat_kind(chat)
        group_title: str | None = getattr(chat, "title", None)

        messages_engine = self._storage._engines[StoreName.MESSAGES]
        if self._source_uuid is None:
            raise RuntimeError("source_uuid not set — on_subscribe incomplete")

        with Session(messages_engine) as session:
            group_id = upsert_group(
                session,
                source_id=self._source_uuid,
                platform_groupid=platform_groupid,
                kind=group_kind,
                title=group_title,
                seen_at=collected_at,
            )
            actor_id = upsert_actor(
                session,
                source_id=self._source_uuid,
                actor_key=actor_key,
                platform_userid=str(sender_id),
                handle=handle,
                display_name=display_name,
                seen_at=sent_at,
            )
            session.commit()

        platform_msgid = str(msg.id)
        evidence_ref = f"telegram:{platform_groupid}:{platform_msgid}"
        body = msg.message
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()

        # Attachment metadata
        attachments: list[AttachmentTable] = []
        has_attachment = bool(msg.media)
        if msg.media:
            att = _extract_attachment_meta(msg.media, new_uuid7())
            if att is not None:
                attachments.append(att)

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
            has_attachment=has_attachment,
            reply_to_msg_id=None,
            forward_of_msg_id=None,
        )

        # Fix attachment message_id FK
        for att in attachments:
            att.message_id = msg_row.id

        written = await self._msg_store.put_message(msg_row, attachments)

        # Always publish to the bus — sensor uses corpus cursors for deduplication,
        # not bus delivery. This ensures backfill re-publishes already-stored messages
        # to a sensor that wasn't running during the original ingest.

        # Publish RawMessageEnvelope
        traceparent = current_traceparent() or _zero_traceparent()
        env = RawMessageEnvelope(
            source=SourceKind.TELEGRAM,
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
            is_forward=bool(msg.fwd_from),
            has_attachment=has_attachment,
            reply_to_platform_msgid=str(msg.reply_to_msg_id) if msg.reply_to_msg_id else None,
            trace_context=TraceContext(traceparent=traceparent),
        )

        await self.publisher.publish(
            subject_for(SourceKind.TELEGRAM, self.instance_id),
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
        return written

    async def health(self) -> CollectorHealth:
        now = _time.monotonic()
        hour_ago = now - 3600
        msgs_last_hour = sum(1 for t in self._recent if t >= hour_ago)

        subs: list[str] = []
        if self._client and self._client.is_connected():
            try:
                async for dialog in self._client.iter_dialogs():
                    subs.append(str(dialog.id))
                    if len(subs) >= _HEALTH_SUBS_CAP:
                        break
            except Exception as exc:
                _log.warning(
                    "collector.health_subs_enumeration_failed",
                    identity=self._identity_name,
                    error=str(exc),
                )

        state = (
            CollectorState.RUNNING
            if (self._client and self._client.is_connected())
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
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as exc:
                _log.warning(
                    "collector.disconnect_failed",
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


def _strip_100(n: int) -> int:
    """Strip the -100 marked-peer prefix if present: -1004964840750 → 4964840750."""
    a = abs(n)
    s = str(a)
    if s.startswith("100") and len(s) > _MARKED_PEER_PREFIX_LEN:
        return int(s[_MARKED_PEER_PREFIX_LEN:])
    return a


def _to_raw_entity_id(s: str) -> int:
    """Parse a numeric config string to a raw positive entity ID.

    Handles: bare positive (3967724335), bare negative (-3967724335),
    and -100-prefixed (-1003967724335). Raises ValueError for non-numeric strings.
    """
    return _strip_100(int(s))


def _chat_raw_id(chat_id: int) -> int:
    """Convert event.chat_id to the raw positive entity ID for filter comparison."""
    return _strip_100(chat_id)


def _parse_proxy(proxy_uri: str | None) -> tuple[int, str | None, int] | None:
    if not proxy_uri:
        return None
    try:
        from urllib.parse import urlparse  # noqa: PLC0415  — lazy: only when proxy_uri set

        import socks  # type: ignore[import-untyped]  # noqa: PLC0415  — lazy PySocks load

        p = urlparse(proxy_uri)
        scheme_map = {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}
        stype = scheme_map.get(p.scheme.lower())
        if stype is None:
            _log.warning("collector.unknown_proxy_scheme", scheme=p.scheme)
            return None
        return (stype, p.hostname, p.port or 1080)
    except Exception as exc:
        _log.warning("collector.proxy_parse_error", error=str(exc))
        return None


def _chat_kind(chat: object) -> GroupKind:
    if isinstance(chat, Channel):
        return GroupKind.CHANNEL if getattr(chat, "broadcast", False) else GroupKind.CHAT
    if isinstance(chat, Chat):
        return GroupKind.CHAT
    if isinstance(chat, User):
        return GroupKind.DM
    return GroupKind.CHAT


def _extract_attachment_meta(
    media: object,
    placeholder_id: UUID,
) -> AttachmentTable | None:
    """Extract attachment metadata without downloading."""
    if isinstance(media, MessageMediaPhoto) and isinstance(media.photo, Photo):
        return AttachmentTable(
            id=placeholder_id,
            message_id=placeholder_id,  # overwritten by caller
            kind=AttachmentKind.IMAGE,
            mime="image/jpeg",
            size_bytes=0,
            sha256="0" * 64,
            filename=None,
            storage_uri=None,
        )
    if isinstance(media, MessageMediaDocument) and isinstance(media.document, Document):
        doc = media.document
        mime = doc.mime_type or "application/octet-stream"
        size = doc.size or 0
        filename = None
        for attr in doc.attributes or []:
            name = getattr(attr, "file_name", None)
            if name:
                filename = name
                break
        kind = _mime_to_kind(mime)
        return AttachmentTable(
            id=placeholder_id,
            message_id=placeholder_id,  # overwritten by caller
            kind=kind,
            mime=mime,
            size_bytes=size,
            sha256="0" * 64,
            filename=filename,
            storage_uri=None,
        )
    return None


def _mime_to_kind(mime: str) -> AttachmentKind:
    if mime.startswith("image/"):
        return AttachmentKind.IMAGE
    if mime.startswith("video/"):
        return AttachmentKind.VIDEO
    if mime.startswith("audio/"):
        return AttachmentKind.AUDIO
    return AttachmentKind.DOCUMENT


__all__ = ["TelegramCollector"]
