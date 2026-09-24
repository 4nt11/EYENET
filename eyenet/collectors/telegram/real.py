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
import json
import time as _time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

import structlog
from opentelemetry import trace
from sqlalchemy.exc import SQLAlchemyError
from telethon import TelegramClient, errors, events
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

from eyenet.collectors.base._credentials import materialize_telegram_session
from eyenet.collectors.base.skeleton import CollectorSkeleton, VisibleGroup
from eyenet.collectors.telegram._join import (
    CollectorJoinHandler,
    JoinAction,
    JoinOutcome,
    candidate_match_forms,
    classify_join_error,
    parse_invite_hash,
    select_join_action,
)
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
from eyenet.contracts.supervisor import (
    BackfillCommand,
    JoinGroupCommand,
    LeaveGroupCommand,
    ScanVisibleGroupsCommand,
    command_subject_for,
)
from eyenet.identity_pool.loader import IdentityFileEntry

if TYPE_CHECKING:
    from cryptography.fernet import Fernet
from eyenet.models import AttachmentTable, MessageTable
from eyenet.models._base import new_uuid7
from eyenet.services.discovery.scout_graduation import ScoutGraduationService
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.propagation import current_traceparent

_log = structlog.get_logger()
_tracer = trace.get_tracer("eyenet.collector.telegram")

# max subscriptions returned in health()
_HEALTH_SUBS_CAP = 100
# length of the "100" marked-peer prefix in stringified Telegram peer IDs
_MARKED_PEER_PREFIX_LEN = 3
# Low-cadence backstop: at most one REQUESTED-membership probe sweep per this
# many seconds, regardless of the runner's tick_interval. The event path is the
# primary detector; the probe just catches approvals that arrived silently.
_REQUESTED_PROBE_INTERVAL_S = 300.0


def _zero_traceparent() -> str:
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


class TelegramCollector(CollectorSkeleton):
    """Telethon-based real Telegram collector."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        pool: IdentityPool,
        identity_name: str,
        backfill: bool = False,
        session_key: Fernet | None = None,
    ) -> None:
        super().__init__(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name=identity_name,
            source_kind=SourceKind.TELEGRAM,
        )
        # Decrypts the session blob at boot (DB pool). None = legacy plaintext
        # file pool, where session_path is opened by Telethon directly.
        self._session_key = session_key
        self._client: TelegramClient | None = None
        self._source_uuid: UUID | None = None
        # Raw positive entity IDs (Channel.id / Chat.id) — the only form
        # that's consistent across get_entity(), dialog.entity.id, and
        # abs(event.chat_id). dialog.id and event.chat_id use varying
        # negative forms depending on Telethon version.
        # Fail-CLOSED: a live account SEES every dialog it's in, so the monitor
        # set starts EMPTY (ingest nothing) and is filled only by explicit
        # monitor_groups config + this collector's active memberships (groups the
        # operator joined via /monitored-groups). There is deliberately no
        # "monitor everything" mode: that is the firehose + ban risk we reject.
        self._monitor_raw_ids: set[int] = set()
        self._backfill = backfill
        self._recent: deque[float] = deque(maxlen=3600)
        # E5 discovery recursion: this collector's own DB row + the join core.
        self._collector_id: UUID | None = None
        self._join: CollectorJoinHandler | None = None
        # Held ref to the on-start visible-group scan task (RUF006: the loop only
        # weak-refs tasks, so a bare create_task can be GC'd mid-run).
        self._scan_task: asyncio.Task[None] | None = None
        self._backfill_task: asyncio.Task[None] | None = None
        # Monotonic timestamp of the last REQUESTED-membership probe sweep.
        self._last_requested_probe: float = 0.0
        # Hot-path guard (Defect 6): lowercased event-matchable platform_groupid
        # forms of this collector's REQUESTED candidates. Empty ⇒ _maybe_confirm
        # does ZERO DB work per message. Refreshed in tick(); seeded in
        # on_subscribe. joinchat: candidates are NOT here (probe-only, Defect 1).
        self._requested_match_forms: set[str] = set()

    async def on_subscribe(self) -> None:  # noqa: PLR0915 — cohesive boot sequence
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

        # Decrypt-on-boot: the blob at session_path is Fernet-encrypted; this
        # yields an in-memory StringSession (DB pool) or the plaintext path
        # (legacy file pool). Plaintext never touches disk on the DB path.
        session = materialize_telegram_session(entry, self._session_key)

        self._client = TelegramClient(
            session,
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
                        resolved.add(entity.id)
                        _log.info("collector.group_resolved", username=g, entity_id=entity.id)
                    except Exception as exc:
                        _log.warning("collector.group_resolve_failed", group=g, error=str(exc))
            self._monitor_raw_ids.update(resolved)

        self._source_uuid = await self._storage.upsert_source(
            kind=SourceKind.TELEGRAM,
            display_name=f"telegram:{entry.name}",
            created_at=datetime.now(tz=UTC),
        )

        # Subscribe to panic kill-switch (PLAN §6.2).
        async def _on_panic(_subject: str, _payload: bytes, _headers: dict[str, str]) -> None:
            _log.warning("collector.panic_received", identity=self._identity_name)
            await self._pool.freeze_all()
            await self.shutdown()

        await self._bus.subscribe("eyenet.control.global.panic", _on_panic)

        # E5 discovery recursion: resolve our own collector row + wire the join
        # core, then subscribe to the command channel keyed by our instance_id
        # (the supervisor publishes JoinGroupCommand here for the leased scout).
        collector = await self._storage.resolve_collector_by_instance_id(self.instance_id)
        self._collector_id = collector.id if collector is not None else None

        # Seed the monitor set from this collector's active memberships (the
        # groups the operator joined via /monitored-groups), unioned onto any
        # static monitor_groups config above. This is the ONLY way an account
        # with no config monitors anything; without a resolvable collector row
        # the set stays empty (fail-closed) and nothing is ingested. Live joins
        # extend the set (_handle_join / _maybe_confirm_requested); leave
        # discards.
        if self._collector_id is not None:
            for m in await self._storage.list_active_memberships(collector_id=self._collector_id):
                grp = await self._storage.get_group(m.group_id)
                if grp is None:
                    continue
                try:
                    self._monitor_raw_ids.add(_to_raw_entity_id(grp.platform_groupid))
                except ValueError:
                    try:
                        entity = await self._client.get_entity(grp.platform_groupid)
                        self._monitor_raw_ids.add(entity.id)
                    except Exception as exc:
                        _log.warning(
                            "collector.monitor_seed_resolve_failed",
                            group=grp.platform_groupid,
                            error=str(exc),
                        )
        self._join = CollectorJoinHandler(
            storage=self._storage,
            audit=self.audit,
            pool=self._pool,
            scout_graduation=ScoutGraduationService(bus=self._bus, storage=self._storage),
            identity_name=self._identity_name,
        )

        async def _on_command(_subject: str, payload: bytes, _headers: dict[str, str]) -> None:
            try:
                kind = json.loads(payload).get("kind")
                if kind == "scan_visible_groups":
                    ScanVisibleGroupsCommand.model_validate_json(payload)
                    if self._source_uuid is not None:
                        await self.scan_visible_groups(source_id=self._source_uuid)
                elif kind == "leave_group":
                    await self._handle_leave(LeaveGroupCommand.model_validate_json(payload))
                elif kind == "backfill":
                    BackfillCommand.model_validate_json(payload)
                    # Long-running: replay history off the command handler. Held
                    # ref so the loop's weak task ref can't GC it (RUF006).
                    self._backfill_task = asyncio.create_task(self._run_backfill())
                else:
                    await self._handle_join(JoinGroupCommand.model_validate_json(payload))
            except Exception as exc:
                _log.error("collector.command_error", error=str(exc))

        await self._bus.subscribe(command_subject_for(self.instance_id), _on_command)

        # Scan the identity's visible groups on start so /monitored-groups reflects
        # everything this account can see (non-blocking). Hold the reference so the
        # loop's weak task ref can't GC it mid-run (RUF006).
        self._scan_task = asyncio.create_task(self._scan_on_start())

        # Seed the hot-path REQUESTED match-form set (Defect 6) so the very
        # first messages after a restart can confirm a pending approval without
        # waiting for the first tick().
        await self._refresh_requested_match_forms()

        _log.info(
            "collector.ready",
            identity=entry.name,
            instance_id=self.instance_id,
            monitor_raw_ids=sorted(self._monitor_raw_ids),
            monitored_count=len(self._monitor_raw_ids),
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

    async def _resolve_join_target(
        self, cmd: JoinGroupCommand
    ) -> tuple[JoinAction, str | None] | None:
        """Map the command's selected access artifact to a (action, invite_hash)
        pair, or ``None`` if the candidate was already failed (E5.5).

        No artifact → the public-identifier path. Returns ``None`` after failing
        the candidate for a missing artifact, an unsupported kind, or an
        unparseable invite — the caller just returns when it sees ``None``."""
        if self._join is None:  # pragma: no cover — guarded by caller
            raise RuntimeError("join handler not ready")
        if cmd.access_artifact_id is None:
            return JoinAction.PUBLIC, None
        artifact = await self._storage.get_group_access_artifact(cmd.access_artifact_id)
        if artifact is None:
            await self._join.fail_candidate(cmd, reason="access_artifact_not_found")
            return None
        action = select_join_action(artifact.kind)
        if action is JoinAction.UNSUPPORTED:
            await self._join.fail_candidate(cmd, reason="unsupported_access_artifact")
            return None
        if action is JoinAction.INVITE_HASH:
            invite_hash = parse_invite_hash(artifact.value)
            if invite_hash is None:
                await self._join.fail_candidate(cmd, reason="unparseable_invite")
                return None
            return action, invite_hash
        return action, None

    async def _handle_join_error(self, cmd: JoinGroupCommand, exc: BaseException) -> None:
        """Route a telethon join failure onto the candidate state machine (E5.5):
        ban → quarantine + burn scout; request-sent → requested; otherwise fail
        (writing a dead-link verdict back onto the artifact when one was used)."""
        if self._join is None:  # pragma: no cover — guarded by caller
            raise RuntimeError("join handler not ready")
        exc_name = type(exc).__name__
        outcome = classify_join_error(exc_name)
        if outcome is JoinOutcome.BANNED:
            await self._join.quarantine_on_ban(cmd)
        elif outcome is JoinOutcome.REQUESTED:
            await self._join.mark_join_requested(cmd, reason=f"{exc_name}: {exc}")
            # FIX 3 — the candidate just became REQUESTED at runtime. Seed its
            # event-matchable forms into the hot-path set NOW so the event path
            # is live immediately, instead of being hollow until the next tick()
            # (≤_REQUESTED_PROBE_INTERVAL_S away). Add the specific forms (same
            # lowercased shape as _refresh_requested_match_forms) rather than a
            # full DB round-trip on the dispatch path. joinchat: candidates
            # produce no event-matchable form (probe-only, Defect 1) — they're
            # simply not added.
            gid = cmd.platform_groupid
            if not gid.startswith("joinchat:"):
                self._requested_match_forms.add(gid.lower())
        else:
            if cmd.access_artifact_id is not None:
                await self._join.record_artifact_validation(cmd.access_artifact_id, exc_name)
            await self._join.fail_candidate(cmd, reason=f"{exc_name}: {exc}")

    async def _resolve_public_entity(self, platform_groupid: str) -> object:
        """Resolve a public-identifier group to a telethon entity for joining.

        An ``@username`` resolves directly. A bare numeric id (a group with no
        public username) is NOT resolvable via ``get_entity(str)`` — telethon
        holds no access_hash for a raw id — so fall back to the account's dialog
        list, which carries the access_hash for every group the account is
        already a member of (the common case for join-at-will over visible
        groups). ``iter_dialogs`` per numeric join is fine at operator cadence.
        """
        if self._client is None:
            raise RuntimeError("client not attached")
        try:
            return await self._client.get_entity(platform_groupid)
        except (ValueError, TypeError):
            raw = _to_raw_entity_id(platform_groupid)  # raises ValueError if @username
            async for dialog in self._client.iter_dialogs():
                ent = dialog.entity
                ent_id = getattr(ent, "id", None)
                if isinstance(ent_id, int) and _strip_100(ent_id) == raw:
                    return ent
            raise ValueError(
                f"no dialog matches group id {platform_groupid!r} "
                "(account is not a member and the id has no public username)"
            ) from None

    async def _handle_join(self, cmd: JoinGroupCommand) -> None:
        """Execute a supervisor-dispatched join (E5/E5.5, §4.12.4).

        Live telethon path (coverage-omitted, §3.4); the DB/transition logic
        lives in the tested :class:`CollectorJoinHandler` + the pure ``_join``
        helpers. The public-identifier path issues ``JoinChannelRequest`` on
        ``platform_groupid``; the invite-link path (E5.5) resolves the selected
        access artifact, parses its hash, and issues ``ImportChatInviteRequest``."""
        if self._join is None or self._source_uuid is None:
            raise RuntimeError("join requested before on_subscribe completed")
        if self._collector_id is None:
            await self._join.fail_candidate(cmd, reason="collector_not_provisioned")
            return
        if self._client is None:
            raise RuntimeError("join requested before telethon client started")

        target = await self._resolve_join_target(cmd)
        if target is None:
            return  # candidate already failed inside _resolve_join_target
        action, invite_hash = target

        # Lazy telethon imports keep _join.py import-free / testable.
        from telethon.tl.functions.channels import JoinChannelRequest  # noqa: PLC0415
        from telethon.tl.functions.messages import ImportChatInviteRequest  # noqa: PLC0415

        try:
            if action is JoinAction.INVITE_HASH:
                updates = await self._client(ImportChatInviteRequest(invite_hash))
                entity = updates.chats[0]
            else:
                entity = await self._resolve_public_entity(cmd.platform_groupid)
                await self._client(JoinChannelRequest(entity))
        except Exception as exc:
            await self._handle_join_error(cmd, exc)
            return

        group_id = await self._join.finalize_joined(
            cmd,
            source_uuid=self._source_uuid,
            collector_id=self._collector_id,
            kind=_chat_kind(entity),
            title=getattr(entity, "title", None),
        )
        # Observe the freshly joined group on the live session (else the 7-day
        # graduation window sees no traffic). None => we already watch all.
        if group_id is None:
            # FIX 4 — finalize_joined lost the CAS (already-finalized / a
            # concurrent caller settled this candidate). Do NOT log a success
            # line with group_id="None"; emit a distinct, accurate INFO.
            _log.info(
                "collector.join_already_finalized",
                candidate_id=str(cmd.candidate_id),
            )
            return
        raw_id = getattr(entity, "id", None)
        if isinstance(raw_id, int):
            self._monitor_raw_ids.add(raw_id)
        _log.info(
            "collector.join_complete",
            candidate_id=str(cmd.candidate_id),
            group_id=str(group_id),
        )

    async def _refresh_requested_match_forms(self) -> None:
        """Rebuild the hot-path event-matchable form set (Defect 6).

        For each REQUESTED candidate assigned to this collector, add the
        event-matchable forms of its ``platform_groupid`` (numeric → str; an
        ``@username``/bare-username, lowercased — Defect 2). ``joinchat:``
        candidates are deliberately SKIPPED: their hash is not recoverable from a
        live ``event.chat_id``, so they are PROBE-ONLY (Defect 1). When the set
        is empty, ``_maybe_confirm_requested`` does zero DB work per message."""
        if self._collector_id is None:
            return
        candidates = await self._storage.requested_candidates_for_collector(self._collector_id)
        forms: set[str] = set()
        for candidate in candidates:
            gid = candidate.platform_groupid
            if gid.startswith("joinchat:"):
                continue  # probe-only (Defect 1)
            forms.add(gid.lower())
        self._requested_match_forms = forms

    def _event_match_forms(self, event: events.NewMessage.Event, chat: object) -> list[str]:
        """Lowercased forms the arriving chat could match a REQUESTED candidate by.

        Numeric (signed + -100-stripped) + the chat ``@username`` forms, built by
        the pure telethon-free :func:`candidate_match_forms` (unit-tested) so the
        case-folding (Defect 2) is exercised in coverage. ``joinchat:`` candidates
        are unreachable here by construction — probe-only (Defect 1)."""
        username = getattr(chat, "username", None)
        return candidate_match_forms(event.chat_id, username if isinstance(username, str) else None)

    async def _maybe_confirm_requested(self, event: events.NewMessage.Event) -> None:
        """Event-path approval detector (E5.6): a message arriving from a group
        this collector requested-to-join means the request was approved — flip
        the REQUESTED candidate to JOINED via the tested core.

        Hot-path-cheap (Defect 6): the cheap numeric forms are checked against the
        in-memory ``_requested_match_forms`` set FIRST; only on a hit (or a
        possible username match) do we pay ``get_chat()`` + the DB query. Empty
        set ⇒ zero DB work."""
        if self._join is None or self._collector_id is None or not self._requested_match_forms:
            return
        # Cheap pre-filter: numeric forms need no get_chat(). No numeric hit AND
        # no @username candidate requested at all ⇒ skip the get_chat() + DB.
        numeric_forms = candidate_match_forms(event.chat_id, None)
        numeric_hit = any(f in self._requested_match_forms for f in numeric_forms)
        username_possible = any(f.startswith("@") for f in self._requested_match_forms)
        if not numeric_hit and not username_possible:
            return
        chat = await event.get_chat()
        for form in self._event_match_forms(event, chat):
            if form not in self._requested_match_forms:
                continue
            candidate = await self._storage.requested_candidate_for_group(
                collector_id=self._collector_id, platform_groupid=form
            )
            if candidate is None:
                continue
            confirmed = await self._join.confirm_requested_membership(candidate.id)
            if confirmed:
                self._monitor_raw_ids.add(_chat_raw_id(event.chat_id))
                self._requested_match_forms.discard(form)
                _log.info(
                    "collector.requested_join_confirmed",
                    candidate_id=str(candidate.id),
                    via="event",
                )
            return

    async def tick(self) -> None:
        """Periodic heartbeat. Refreshes the hot-path match-form set (Defect 6)
        and runs the low-cadence REQUESTED-membership probe backstop (E5.6) — the
        event path is primary; this catches approvals that produced no observed
        message AND is the ONLY path that can confirm invite-link candidates."""
        await self._refresh_requested_match_forms()
        await self._probe_requested_memberships()

    async def _probe_requested_memberships(self) -> None:
        """Backstop approval detector: for each REQUESTED candidate assigned to
        this collector, probe GENUINE live membership and, on confirmation, flip
        it JOINED via the same tested core the event path uses.

        Throttled to one sweep per ``_REQUESTED_PROBE_INTERVAL_S``. Per-candidate
        isolation (Defect 5): one bad candidate (missing collector / telethon
        error) is logged and skipped, never aborting the sweep."""
        if self._join is None or self._collector_id is None or self._client is None:
            return
        now = _time.monotonic()
        if now - self._last_requested_probe < _REQUESTED_PROBE_INTERVAL_S:
            return
        self._last_requested_probe = now

        candidates = await self._storage.requested_candidates_for_collector(self._collector_id)
        for candidate in candidates:
            try:
                await self._probe_one_requested(candidate)
            except (RuntimeError, errors.RPCError, ValueError, SQLAlchemyError) as exc:
                # Defect 5 / FIX 2: one bad candidate must not starve the rest.
                # Every telethon call in the per-candidate probe (incl.
                # get_entity) is INSIDE this guarded body. telethon raises a
                # plain ValueError — not an RPCError — for an unresolvable /
                # deleted / renamed username, so one dead channel must NOT abort
                # the whole sweep. The confirm path also hits storage
                # (open_membership), which can raise SQLAlchemyError (e.g.
                # OperationalError "database is locked", IntegrityError) — that
                # too must NOT abort the sweep; the candidate self-heals next
                # sweep (compensation already rolled it back to REQUESTED before
                # re-raising). Specific tuple (never bare Exception, never
                # try/except/pass): log + continue.
                _log.warning(
                    "collector.requested_probe_candidate_error",
                    candidate_id=str(candidate.id),
                    error=str(exc),
                )

    async def _probe_one_requested(self, candidate: object) -> None:
        """Probe + confirm a single REQUESTED candidate (Defect 1 + 3).

        ``joinchat:<hash>`` → resolve the invite via ``CheckChatInviteRequest``;
        only a ``ChatInviteAlready`` (we ARE a member) confirms — its ``.chat``
        carries the real numeric id + title, passed through so the membership
        opens against the resolved group. ``@username``/numeric → resolve the
        entity then ``GetParticipantRequest(channel, 'me')``; membership is proven
        only when that succeeds (Defect 3 — resolvability ≠ membership). Anything
        else leaves the candidate REQUESTED for the next sweep."""
        if self._join is None or self._client is None:  # pragma: no cover — guarded
            return
        candidate_id = cast("UUID", candidate.id)  # type: ignore[attr-defined]
        platform_groupid = cast("str", candidate.platform_groupid)  # type: ignore[attr-defined]

        if platform_groupid.startswith("joinchat:"):
            confirmed = await self._confirm_joinchat_candidate(candidate_id, platform_groupid)
        else:
            confirmed = await self._confirm_public_candidate(candidate_id, platform_groupid)
        if confirmed:
            self._requested_match_forms.discard(platform_groupid.lower())
            _log.info(
                "collector.requested_join_confirmed",
                candidate_id=str(candidate_id),
                via="probe",
            )

    async def _confirm_joinchat_candidate(self, candidate_id: UUID, platform_groupid: str) -> bool:
        """Invite-link (``joinchat:<hash>``) probe (Defect 1).

        ``CheckChatInviteRequest(hash)`` → ``ChatInviteAlready`` means the scout
        is already a member (the approval landed); its ``.chat`` is the real
        resolved group. A plain ``ChatInvite`` (still pending) or any error means
        not yet approved → no confirmation."""
        if self._join is None or self._client is None:  # pragma: no cover — guarded
            return False
        from telethon.tl.functions.messages import CheckChatInviteRequest  # noqa: PLC0415
        from telethon.tl.types import ChatInviteAlready  # noqa: PLC0415

        invite_hash = platform_groupid[len("joinchat:") :]
        invite = await self._client(CheckChatInviteRequest(invite_hash))
        if not isinstance(invite, ChatInviteAlready):
            return False  # still pending (ChatInvite) — not yet a member
        chat = invite.chat
        resolved_id = getattr(chat, "id", None)
        if not isinstance(resolved_id, int):
            return False
        return await self._join.confirm_requested_membership(
            candidate_id,
            kind=_chat_kind(chat),
            title=getattr(chat, "title", None),
            resolved_platform_groupid=str(_strip_100(resolved_id)),
        )

    async def _confirm_public_candidate(self, candidate_id: UUID, platform_groupid: str) -> bool:
        """Public/numeric candidate probe (Defect 3 — GENUINE membership only).

        Resolve the entity, then ``GetParticipantRequest(channel, 'me')``: a
        ``UserNotParticipantError`` means we are NOT a member (resolvability of a
        public channel is not membership) → no confirmation. Success ⇒ member."""
        if self._join is None or self._client is None:  # pragma: no cover — guarded
            return False
        from telethon.tl.functions.channels import GetParticipantRequest  # noqa: PLC0415

        entity = await self._client.get_entity(platform_groupid)
        try:
            await self._client(GetParticipantRequest(entity, "me"))
        except errors.UserNotParticipantError:
            return False  # resolvable but not a member — stays REQUESTED
        return await self._join.confirm_requested_membership(candidate_id)

    async def _ingest_message(self, event: events.NewMessage.Event) -> None:
        """Live handler: filter, extract, delegate to _ingest_msg."""
        # _maybe_confirm_requested MUST run before the monitor filter: a freshly
        # APPROVED group is not yet in _monitor_raw_ids (it's added on
        # confirmation), so the filter would otherwise drop the very message that
        # proves the approval. The Defect-6 hot-path set makes this near-free
        # (a set lookup; zero DB work when no REQUESTED candidates exist).
        await self._maybe_confirm_requested(event)
        # Fail-closed gate: drop any message from a group not in the monitor set
        # (empty set => ingest nothing). This is what stops the live-account
        # firehose.
        if _chat_raw_id(event.chat_id) not in self._monitor_raw_ids:
            return
        msg = event.message
        if not msg or not msg.message:
            return
        sender = await event.get_sender()
        chat = await event.get_chat()
        await self._ingest_msg(msg, chat_id=event.chat_id, sender=sender, chat=chat)

    async def enumerate_visible_groups(self) -> list[VisibleGroup]:
        """Every group/channel this identity's account is in (its dialogs).

        Skips DMs/users. Prefers ``@username`` as the platform id (resolvable by
        any client for a public group); falls back to the raw entity id."""
        if self._client is None:
            raise RuntimeError("enumerate_visible_groups called before client attached")
        out: list[VisibleGroup] = []
        async for dialog in self._client.iter_dialogs():
            if getattr(dialog, "is_user", False):
                continue
            entity = dialog.entity
            username = getattr(entity, "username", None)
            pgid = f"@{username}" if username else str(getattr(entity, "id", "") or "")
            if not pgid or pgid == "@None":
                continue
            out.append(
                VisibleGroup(
                    platform_groupid=pgid,
                    kind=_chat_kind(entity),
                    title=getattr(dialog, "title", None) or None,
                    is_member=True,
                    member_count=getattr(entity, "participants_count", None),
                )
            )
        return out

    async def _handle_leave(self, cmd: LeaveGroupCommand) -> None:
        """Leave a group on the platform (delete the dialog). The membership close +
        candidate park are done API-side (optimistic, like join); this is the
        best-effort platform-side departure."""
        if self._client is None:
            return
        group = await self._storage.get_group(cmd.group_id)
        if group is None:
            _log.warning("collector.leave_unknown_group", group_id=str(cmd.group_id))
            return
        try:
            entity = await self._client.get_entity(group.platform_groupid)
            await self._client.delete_dialog(entity)
            raw_id = getattr(entity, "id", None)
            if isinstance(raw_id, int):
                self._monitor_raw_ids.discard(raw_id)  # stop gating on a group we left
            _log.info("collector.left_group", group_id=str(cmd.group_id), reason=cmd.reason)
        except Exception as exc:
            _log.warning("collector.leave_failed", group_id=str(cmd.group_id), error=str(exc))

    async def _scan_on_start(self) -> None:
        """One-shot visible-group scan after connect (fire-and-forget helper)."""
        if self._source_uuid is None:
            return
        try:
            await self.scan_visible_groups(source_id=self._source_uuid)
        except Exception as exc:
            _log.warning("collector.scan_on_start_failed", error=str(exc))

    async def _run_backfill(self) -> None:
        """Replay historical messages oldest-first for each monitored group.

        Uses iter_dialogs to resolve proper InputPeer entities — passing raw
        integers to iter_messages is unreliable because Telethon's entity cache
        may not map bare IDs to the right peer type (Channel vs Chat).
        """
        if self._client is None:
            raise RuntimeError("backfill called before on_subscribe attached a client")
        if not self._monitor_raw_ids:
            _log.warning("collector.backfill_skipped", reason="no monitored groups to backfill")
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
        """Core ingest: persist + publish one message. Returns True if written.

        Trace root: every inbound Telegram message produces one
        ``collector.ingest`` span. ``current_traceparent()`` inside the
        publish below reads this span, so downstream subscribers (sensor,
        engine, linker, verifier, graph) parent to it via header propagation.
        """
        with _tracer.start_as_current_span(
            "collector.ingest",
            attributes={
                "service.name": self.name,
                "service.instance_id": self.instance_id,
                "source.platform": "telegram",
                "source.id": str(self._source_uuid) if self._source_uuid else "",
                "message.platform_msgid": str(msg.id),
                "message.platform_groupid": str(chat_id),
            },
        ) as span:
            return await self._ingest_msg_inner(
                msg, chat_id=chat_id, sender=sender, chat=chat, span=span
            )

    async def _ingest_msg_inner(
        self,
        msg: TLMessage,
        *,
        chat_id: int,
        sender: object,
        chat: object,
        span: trace.Span,
    ) -> bool:
        sent_at = msg.date.replace(tzinfo=UTC) if msg.date.tzinfo is None else msg.date
        collected_at = datetime.now(tz=UTC)

        # --- authorship (§forward-attribution) ---
        # A forward's author is its ORIGIN (the real content author), not the
        # relay; a channel-broadcast's author is not an individual. Both are kept
        # out of stylometric profiling below.
        author = _authorship(msg, sender)
        actor_key = author.actor_key
        handle = author.handle
        display_name = author.display_name

        # --- chat metadata ---
        platform_groupid = str(chat_id)
        group_kind = _chat_kind(chat)
        group_title: str | None = getattr(chat, "title", None)

        if self._source_uuid is None:
            raise RuntimeError("source_uuid not set — on_subscribe incomplete")

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
            platform_userid=author.platform_userid,
            handle=handle,
            display_name=display_name,
            seen_at=sent_at,
        )

        platform_msgid = str(msg.id)
        evidence_ref = f"telegram:{platform_groupid}:{platform_msgid}"
        span.set_attribute("message.evidence_ref", evidence_ref)
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
        # For a forward, the actor IS the origin author, so record it as the
        # forward origin and note the relay (the reposter) in source_specific.
        source_specific: dict[str, object] = {}
        if author.relayed_by_platform_userid is not None:
            source_specific["relayed_by_platform_userid"] = author.relayed_by_platform_userid
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
            forward_origin_actor_id=actor_id if author.is_forward else None,
            source_specific=source_specific,
        )

        # Fix attachment message_id FK
        for att in attachments:
            att.message_id = msg_row.id

        written = await self._storage.put_message(msg_row, attachments)

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

        # Stylometric gate: only an individual's OWN words feed the profiler. A
        # forward (text authored elsewhere) or a channel-broadcast (no individual
        # author) is stored as evidence but NOT published to the sensor, so it
        # can't poison an actor's writing-style profile.
        if not (author.is_forward or author.is_channel_author):
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


@dataclass(frozen=True)
class _Authorship:
    """Who a message is attributed to, and how it got here.

    For a plain post the author IS the sender. For a FORWARD the author is the
    forward *origin* (the real content author — a person or a source channel) and
    the sender is only the relay, recorded in ``relayed_by_platform_userid``.
    ``is_channel_author`` marks a non-individual author (channel broadcast /
    anonymous) and ``is_forward`` marks forwarded content — both are excluded from
    stylometric profiling (the text is not the sender's own writing)."""

    actor_key: str
    platform_userid: str
    handle: str | None
    display_name: str | None
    is_forward: bool
    is_channel_author: bool
    relayed_by_platform_userid: str | None


def _actor_key(token: str) -> str:
    return "actor:" + hashlib.sha256(f"telegram||{token}".encode()).hexdigest()


def _fwd_origin_marked_id(from_id: object) -> int | None:
    """Marked peer id (-100… for channels, positive for users) of a forward origin
    ``fwd_from.from_id``, or None when the origin is hidden."""
    if from_id is None:
        return None
    try:
        from telethon import utils as _tl_utils  # noqa: PLC0415

        return int(_tl_utils.get_peer_id(from_id))
    except Exception:
        return None


def _authorship(msg: object, sender: object) -> _Authorship:
    """Resolve message authorship (see :class:`_Authorship`). Pure — operates on
    the telethon message + sender via duck typing, so it is unit-testable."""
    fwd = getattr(msg, "fwd_from", None)
    if fwd is not None:
        relay = str(getattr(msg, "sender_id", 0) or 0)
        from_name = getattr(fwd, "from_name", None)
        origin = _fwd_origin_marked_id(getattr(fwd, "from_id", None))
        if origin is not None:
            uid = str(origin)
            return _Authorship(
                actor_key=_actor_key(uid),
                platform_userid=uid,
                handle=None,
                display_name=from_name,
                is_forward=True,
                is_channel_author=origin < 0,
                relayed_by_platform_userid=relay,
            )
        # Hidden origin: only a display name. Coalesce by name so one hidden source
        # is one actor. No resolvable id, so it is not an individual we can profile.
        name = from_name or "unknown"
        return _Authorship(
            actor_key=_actor_key("fwdname:" + name),
            platform_userid="fwd:" + name,
            handle=None,
            display_name=from_name,
            is_forward=True,
            is_channel_author=True,
            relayed_by_platform_userid=relay,
        )
    sender_id = getattr(msg, "sender_id", 0) or 0
    uid = str(sender_id)
    handle: str | None = None
    display: str | None = None
    if isinstance(sender, User):
        handle = f"@{sender.username}" if sender.username else None
        display = " ".join(filter(None, [sender.first_name, sender.last_name])) or None
    return _Authorship(
        actor_key=_actor_key(uid),
        platform_userid=uid,
        handle=handle,
        display_name=display,
        is_forward=False,
        # Not an individual: channel broadcast / anonymous admin (sender is not a
        # User, or the peer id is a negative channel id).
        is_channel_author=not isinstance(sender, User)
        or (isinstance(sender_id, int) and sender_id < 0),
        relayed_by_platform_userid=None,
    )


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
