# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telethon-free core of the M9.E5 collector join (API_PLAN §4.12.4).

The Telegram collector's command handler (``real.py``) issues the actual
``JoinChannelRequest`` / ``ImportChatInviteRequest`` against telethon, then maps
the outcome onto these helpers. Keeping the DB/transition logic here — with no
telethon import — makes the load-bearing state machine unit-testable and gives
it real coverage credit (``real.py`` itself is coverage-omitted, §3.4).

Outcome of a join attempt:
- success → :meth:`CollectorJoinHandler.finalize_joined` (joining→joined, Group
  + CollectorGroupMembership + ``resulting_group_id``, ``candidate.joined`` audit)
- platform refusal / timeout → :meth:`fail_candidate` (joining→failed)
- ban detected during the join → :meth:`quarantine_on_ban` (joining→failed +
  burn the scout; the candidate never reached ``joined``, so it fails — the
  decision recorded for E5; ``joined→parked`` is reserved for bans detected
  later on the live message/health path).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import (
    ArtifactValidationState,
    CandidateState,
    GroupAccessKind,
    GroupKind,
    IdentityState,
    JoinedVia,
)
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from eyenet.contracts.identity_pool import IdentityPool
    from eyenet.contracts.supervisor import JoinGroupCommand
    from eyenet.services.discovery.scout_graduation import ScoutGraduationService
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter

_log = get_logger()


class JoinOutcome(Enum):
    """How a telethon join error maps onto the candidate state machine."""

    FAILED = "failed"
    BANNED = "banned"
    # Approval-gated group accepted a join *request* (M9.E5.5) — pending, not
    # failed: the candidate goes joining→requested.
    REQUESTED = "requested"


class JoinAction(Enum):
    """Which telethon request the collector should issue for an artifact kind."""

    PUBLIC = "public"  # JoinChannelRequest on the public identifier
    INVITE_HASH = "invite_hash"  # ImportChatInviteRequest on a parsed hash
    UNSUPPORTED = "unsupported"  # fail_candidate("unsupported_access_artifact")


# Unambiguous ban signal — the scout is no longer usable in this group.
_BAN_ERRORS = frozenset({"UserBannedInChannelError"})
# Approval-gated join: the request was sent, awaiting platform-side admin
# approval (candidate joining→requested), distinct from a hard failure.
_JOIN_REQUEST_ERRORS = frozenset({"InviteRequestSentError"})
# Refusals / transient failures: the candidate fails, the scout survives.
_FAIL_ERRORS = frozenset(
    {
        "FloodWaitError",
        "InviteHashExpiredError",
        "InviteHashInvalidError",
        "ChannelPrivateError",
        "ChatWriteForbiddenError",
        "ChannelsTooMuchError",
        "UsernameInvalidError",
        "UsernameNotOccupiedError",
    }
)
# Dead-link verdicts written back onto the access artifact's validation_state so
# the supervisor's selection won't re-offer the same broken invite (M9.E5.5).
_ARTIFACT_STATE_BY_ERROR: dict[str, ArtifactValidationState] = {
    "InviteHashExpiredError": ArtifactValidationState.EXPIRED,
    "InviteHashInvalidError": ArtifactValidationState.REVOKED,
}

# Telegram invite tokens follow `+HASH`, `joinchat/HASH`, or `invite=HASH`
# (covering t.me/+, t.me/joinchat/, and tg://join?invite= forms). The token is
# base64url-ish; a bare public handle (t.me/name, @name) carries none of these
# markers and yields no match. ASCII classes are correct here (telethon hashes
# are ASCII).
_INVITE_HASH_RE = re.compile(r"(?:joinchat/|invite=|\+)([A-Za-z0-9_-]+)")

# Length of the Telegram "100" marked-peer prefix (-100<rawid>).
_MARKED_PEER_PREFIX_LEN = 3


def classify_join_error(exc_name: str) -> JoinOutcome:
    """Map a telethon exception *class name* to a :class:`JoinOutcome`.

    Switches on ``type(exc).__name__`` (a plain string) so this stays import-free
    and testable without telethon installed. Unknown errors default to
    ``FAILED`` — a join we couldn't complete, but not a confirmed ban (we do not
    burn a scout on an error we don't understand)."""
    if exc_name in _BAN_ERRORS:
        return JoinOutcome.BANNED
    if exc_name in _JOIN_REQUEST_ERRORS:
        return JoinOutcome.REQUESTED
    return JoinOutcome.FAILED


def select_join_action(kind: GroupAccessKind) -> JoinAction:
    """Map an access-artifact kind to the join action (M9.E5.5, invite-link scope).

    PUBLIC_IDENTIFIER → public join; INVITE_LINK → invite-hash join. Every other
    kind (QR_CODE, DIRECT_INVITE, PAID_SUBSCRIPTION, ACCESS_BLOCKED,
    RESTRICTED_OTHER) is unsupported for now and fails the candidate cleanly."""
    if kind is GroupAccessKind.PUBLIC_IDENTIFIER:
        return JoinAction.PUBLIC
    if kind is GroupAccessKind.INVITE_LINK:
        return JoinAction.INVITE_HASH
    return JoinAction.UNSUPPORTED


def parse_invite_hash(value: str | None) -> str | None:
    """Extract the invite hash from a Telegram invite-link value, or ``None``.

    Handles ``t.me/+HASH``, ``t.me/joinchat/HASH``, ``tg://join?invite=HASH``
    (with or without scheme/host). Returns ``None`` for a public handle or any
    value that carries no invite token."""
    if not value:
        return None
    match = _INVITE_HASH_RE.search(value)
    return match.group(1) if match else None


def _strip_marked_peer_prefix(n: int) -> int:
    """Strip the Telegram -100 marked-peer prefix: -1004964840750 → 4964840750.

    Mirrors ``real._strip_100`` but lives here (telethon-free) so the
    event-path candidate-form generation is unit-testable. ``abs()`` first, then
    drop a leading ``100`` when it leaves at least one digit."""
    a = abs(n)
    s = str(a)
    if s.startswith("100") and len(s) > _MARKED_PEER_PREFIX_LEN:
        return int(s[_MARKED_PEER_PREFIX_LEN:])
    return a


def candidate_match_forms(chat_id: int, username: str | None) -> list[str]:
    """Lowercased ``platform_groupid`` forms an arriving message could match.

    Discovery stores numeric ids, ``@username`` (lowercased — see
    ``channel_reference_extraction._detect``), or ``joinchat:<hash>``. A live
    message exposes only ``event.chat_id`` (in one of several signed/prefixed
    forms) and the chat's raw ``username``; it can NEVER reconstruct a
    ``joinchat:<hash>`` (the hash is not recoverable from a chat id) — those
    candidates are PROBE-ONLY (Defect 1). This yields the numeric + stripped +
    ``@username``/bare-username forms, lowercased to match how discovery stores
    them (Defect 2: ``@CryptoNews`` → ``@cryptonews``). A falsy username yields
    NO username form (never a broad-matching empty ``@``).

    Pure + telethon-free so it carries coverage; the live ``event.get_chat()``
    call stays in coverage-omitted ``real.py``."""
    forms: list[str] = [str(chat_id), str(_strip_marked_peer_prefix(chat_id))]
    if username:
        lowered = username.lower()
        forms.append(f"@{lowered}")
        forms.append(lowered)
    # Preserve order, drop dups.
    return list(dict.fromkeys(forms))


def artifact_state_for_error(exc_name: str) -> ArtifactValidationState | None:
    """Map a telethon join-error class name to a dead-link validation verdict,
    or ``None`` when the error says nothing about the artifact itself (e.g. a
    FloodWait or a ban — those aren't the link's fault) (M9.E5.5)."""
    return _ARTIFACT_STATE_BY_ERROR.get(exc_name)


class CollectorJoinHandler:
    """Telethon-free DB/transition core invoked by the Telegram collector (E5)."""

    def __init__(
        self,
        *,
        storage: BaseRepository,
        audit: AuditEmitter,
        pool: IdentityPool,
        scout_graduation: ScoutGraduationService,
        identity_name: str,
    ) -> None:
        self._storage = storage
        self._audit = audit
        self._pool = pool
        self._scout_graduation = scout_graduation
        self._identity_name = identity_name

    async def finalize_joined(
        self,
        cmd: JoinGroupCommand,
        *,
        source_uuid: UUID,
        collector_id: UUID,
        kind: GroupKind,
        title: str | None,
        now: datetime | None = None,
    ) -> UUID | None:
        """Record a confirmed platform join (candidate joining→joined).

        Atomically claims the ``joining → joined`` transition (CAS, Defect 4)
        FIRST; only the winner upserts the Group, opens a
        ``joined_via=candidate`` membership carrying the originating
        ``candidate_id``, sets ``resulting_group_id``, and emits
        ``candidate.joined``. Returns the Group id, or ``None`` if the candidate
        was no longer ``joining`` (lost the race / already settled)."""
        return await self._open_joined_membership(
            candidate_id=cmd.candidate_id,
            from_state=CandidateState.JOINING,
            source_uuid=source_uuid,
            collector_id=collector_id,
            platform_groupid=cmd.platform_groupid,
            kind=kind,
            title=title,
            scout_identity_id=cmd.scout_identity_id,
            now=now,
        )

    async def _open_joined_membership(
        self,
        *,
        candidate_id: UUID,
        from_state: CandidateState,
        source_uuid: UUID,
        collector_id: UUID,
        platform_groupid: str,
        kind: GroupKind,
        title: str | None,
        scout_identity_id: UUID | None,
        now: datetime | None = None,
    ) -> UUID | None:
        """Shared confirmed-join writeback (Defect 4 — transition FIRST, atomic).

        Upserts the Group, then ATOMICALLY claims ``from_state → joined`` with
        ``resulting_group_id`` via :meth:`claim_candidate_transition` (a single
        conditional UPDATE). Only the CAS winner opens a ``joined_via=candidate``
        membership and emits ``candidate.joined`` — so a redundant event + probe
        firing for one approval (REQUESTED) or a duplicate join callback
        (JOINING) opens EXACTLY ONE membership and emits exactly one audit.
        Returns the Group id on a win, ``None`` on a loss (no membership opened).

        Reused by :meth:`finalize_joined` (``from_state=JOINING``) and
        :meth:`confirm_requested_membership` (``from_state=REQUESTED``)."""
        at = now or datetime.now(tz=UTC)
        group_id = await self._storage.upsert_group(
            source_id=source_uuid,
            platform_groupid=platform_groupid,
            kind=kind,
            title=title,
            seen_at=at,
        )
        won = await self._storage.claim_candidate_transition(
            candidate_id,
            from_state=from_state,
            to_state=CandidateState.JOINED,
            resulting_group_id=group_id,
        )
        if not won:
            # Lost the CAS (a concurrent caller already settled this candidate,
            # or it left ``from_state``). Open NOTHING — the winner owns the
            # single membership + audit. The upserted Group is harmless (idempotent).
            _log.info(
                "collector.join_cas_lost",
                candidate_id=str(candidate_id),
                from_state=from_state.value,
            )
            return None
        # FIX 1 — the CAS already committed ``from_state → JOINED``. The
        # membership open (durable evidence in main.db) and the audit emit
        # (audit.db / bus) are SEPARATE awaited writes; a failure between them
        # would otherwise leave the candidate permanently JOINED with no
        # membership and no audit, and a retry CAS-loses (state is JOINED) so it
        # never self-heals. Membership FIRST (it is the evidence), audit SECOND.
        try:
            await self._storage.open_membership(
                collector_id=collector_id,
                group_id=group_id,
                joined_at=at,
                joined_via=JoinedVia.CANDIDATE,
                joined_via_candidate_id=candidate_id,
            )
        except Exception:
            # Compensate: roll the candidate back JOINED → ``from_state`` via a
            # raw CAS so the next probe/event sweep retries cleanly. The raw CAS
            # is a conditional UPDATE that does NOT consult the FSM ``_ALLOWED``
            # guard — this compensation edge is a failure rollback only and must
            # NOT be added to the state machine. Loud, never silent: re-raise so
            # the caller's per-candidate guard logs + continues.
            rolled_back = await self._storage.claim_candidate_transition(
                candidate_id,
                from_state=CandidateState.JOINED,
                to_state=from_state,
                resulting_group_id=None,
            )
            _log.warning(
                "collector.join_membership_open_failed_rolled_back",
                candidate_id=str(candidate_id),
                from_state=from_state.value,
                rolled_back=rolled_back,
            )
            raise
        try:
            await self._audit.emit(
                event=AuditSubject.CANDIDATE_JOINED.value,
                subject_kind="candidate",
                subject_id=candidate_id,
                payload={
                    "group_id": str(group_id),
                    "scout_identity_id": (
                        str(scout_identity_id) if scout_identity_id is not None else None
                    ),
                },
            )
        except Exception:
            # Membership (the durable evidence) already exists — do NOT roll
            # back. A missing audit is a lesser, logged inconsistency, not a
            # reason to discard a real join. Loud WARN + re-raise.
            _log.warning(
                "collector.join_audit_emit_failed",
                candidate_id=str(candidate_id),
                group_id=str(group_id),
                note="candidate joined, membership opened, audit emit failed",
            )
            raise
        _log.info(
            "collector.candidate_joined",
            candidate_id=str(candidate_id),
            group_id=str(group_id),
        )
        return group_id

    async def confirm_requested_membership(
        self,
        candidate_id: UUID,
        *,
        kind: GroupKind | None = None,
        title: str | None = None,
        scout_identity_id: UUID | None = None,
        resolved_platform_groupid: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Flip an approval-gated candidate ``requested → joined`` once the join
        is confirmed real (M9.E5.5 → E5.6).

        The group context (source, platform_groupid, assigned collector) is read
        off the candidate row itself — the approval detector only knows *which*
        candidate cleared, not the full join command. ``kind``/``title`` refine
        the upserted Group; ``kind`` falls back to the candidate's ``kind_hint``
        and ``title`` to its ``display_name_hint`` when not supplied.

        GUARDED + IDEMPOTENT + DUAL-CALLER-SAFE (Defect 4): the
        ``requested → joined`` flip is an atomic compare-and-swap done FIRST
        inside :meth:`_open_joined_membership`. A missing candidate, a terminal
        state (rejected/failed/parked), an already-``joined`` one, or a
        concurrent caller that already won the CAS all yield ``False`` (no-op) —
        so a redundant event + probe firing for the same candidate opens exactly
        one membership and emits exactly one ``candidate.joined`` audit. Returns
        ``True`` only when THIS call performed the flip.

        ``platform_groupid``/``source``/collector context is read off the
        candidate row. When the probe resolves an invite-link (``joinchat:``)
        candidate it passes ``resolved_platform_groupid``/``kind``/``title`` from
        the live ``CheckChatInviteRequest`` so the membership opens against the
        REAL numeric group, not the unresolvable ``joinchat:<hash>`` placeholder
        (Defect 1).

        It deliberately does not need a telethon client: the live membership
        *confirmation* (an event arriving / a CheckChatInvite/GetParticipant
        probe) belongs to ``real.py``; the decision + DB writeback live here."""
        candidate = await self._storage.get_candidate(candidate_id)
        if candidate is None or candidate.state is not CandidateState.REQUESTED:
            return False
        if candidate.assigned_collector_id is None:
            # A requested candidate without an assigned collector is a data
            # invariant violation (the join could not have been dispatched);
            # refuse rather than open a membership against an unknown collector.
            raise RuntimeError(
                f"candidate {candidate_id} is REQUESTED but has no assigned_collector_id"
            )
        group_id = await self._open_joined_membership(
            candidate_id=candidate_id,
            from_state=CandidateState.REQUESTED,
            source_uuid=candidate.source_id,
            collector_id=candidate.assigned_collector_id,
            platform_groupid=(
                resolved_platform_groupid
                if resolved_platform_groupid is not None
                else candidate.platform_groupid
            ),
            kind=kind if kind is not None else (candidate.kind_hint or GroupKind.CHANNEL),
            title=title if title is not None else candidate.display_name_hint,
            scout_identity_id=scout_identity_id,
            now=now,
        )
        return group_id is not None

    async def fail_candidate(self, cmd: JoinGroupCommand, *, reason: str) -> None:
        """Record a refused/failed join (candidate joining→failed). The scout
        survives — the failure is the candidate's, not the identity's."""
        await self._storage.transition_candidate(
            candidate_id=cmd.candidate_id,
            to_state=CandidateState.FAILED,
            rejection_reason=reason,
        )
        await self._audit.emit(
            event=AuditSubject.CANDIDATE_FAILED.value,
            subject_kind="candidate",
            subject_id=cmd.candidate_id,
            payload={"reason": reason},
        )
        _log.warning(
            "collector.candidate_failed", candidate_id=str(cmd.candidate_id), reason=reason
        )

    async def mark_join_requested(
        self, cmd: JoinGroupCommand, *, reason: str = "join_request_sent"
    ) -> None:
        """Record a pending approval-gated join (candidate joining→requested).

        The scout sent a join *request* (telethon ``InviteRequestSentError``);
        a platform admin must approve it. The candidate is not failed — it waits
        in ``requested`` until the (future) approval detector resolves it."""
        await self._storage.transition_candidate(
            candidate_id=cmd.candidate_id,
            to_state=CandidateState.REQUESTED,
            rejection_reason=reason,
        )
        await self._audit.emit(
            event=AuditSubject.CANDIDATE_JOIN_REQUESTED.value,
            subject_kind="candidate",
            subject_id=cmd.candidate_id,
            payload={"reason": reason, "scout_identity_id": str(cmd.scout_identity_id)},
        )
        _log.info(
            "collector.candidate_join_requested",
            candidate_id=str(cmd.candidate_id),
            reason=reason,
        )

    async def record_artifact_validation(
        self, artifact_id: UUID, exc_name: str, *, now: datetime | None = None
    ) -> None:
        """Write a dead-link verdict back onto the access artifact (M9.E5.5).

        No-op unless ``exc_name`` maps to a validation state (expired/revoked) —
        a flood-wait or ban says nothing about the link itself, so the artifact
        is left untouched. Idempotent and best-effort: the candidate failure is
        recorded separately by the caller regardless."""
        state = artifact_state_for_error(exc_name)
        if state is None:
            return
        await self._storage.set_artifact_validation_state(
            artifact_id=artifact_id,
            validation_state=state,
            last_validated_at=now or datetime.now(tz=UTC),
        )
        _log.info(
            "collector.artifact_validation_recorded",
            artifact_id=str(artifact_id),
            validation_state=state.value,
        )

    async def quarantine_on_ban(
        self, cmd: JoinGroupCommand, *, reason: str = "banned_on_join"
    ) -> None:
        """Handle a ban detected during the join: fail the candidate (it never
        reached ``joined``) and burn the scout via the graduation service, then
        reflect the burn in the file pool so restart-recovery can't re-offer it."""
        await self.fail_candidate(cmd, reason=reason)
        await self._scout_graduation.quarantine_scout(
            identity_id=cmd.scout_identity_id,
            reason=reason,
            candidate_id=cmd.candidate_id,
        )
        try:
            await self._pool.release(self._identity_name, new_state=IdentityState.BURNED)
        except KeyError as exc:
            # File pool doesn't know this identity name — the DB burn above is
            # authoritative; log and move on (don't mask the burn).
            _log.warning(
                "collector.pool_burn_release_failed",
                identity=self._identity_name,
                error=str(exc),
            )


__all__ = [
    "CollectorJoinHandler",
    "JoinAction",
    "JoinOutcome",
    "artifact_state_for_error",
    "candidate_match_forms",
    "classify_join_error",
    "parse_invite_hash",
    "select_join_action",
]
