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
    ) -> UUID:
        """Record a confirmed platform join (candidate joining→joined).

        Upserts the Group, opens a ``joined_via=candidate`` membership carrying
        the originating ``candidate_id``, sets the candidate's
        ``resulting_group_id``, and emits ``candidate.joined``. Returns the
        Group id."""
        at = now or datetime.now(tz=UTC)
        group_id = await self._storage.upsert_group(
            source_id=source_uuid,
            platform_groupid=cmd.platform_groupid,
            kind=kind,
            title=title,
            seen_at=at,
        )
        await self._storage.open_membership(
            collector_id=collector_id,
            group_id=group_id,
            joined_at=at,
            joined_via=JoinedVia.CANDIDATE,
            joined_via_candidate_id=cmd.candidate_id,
        )
        await self._storage.transition_candidate(
            candidate_id=cmd.candidate_id,
            to_state=CandidateState.JOINED,
            resulting_group_id=group_id,
        )
        await self._audit.emit(
            event=AuditSubject.CANDIDATE_JOINED.value,
            subject_kind="candidate",
            subject_id=cmd.candidate_id,
            payload={
                "group_id": str(group_id),
                "scout_identity_id": str(cmd.scout_identity_id),
            },
        )
        _log.info(
            "collector.candidate_joined",
            candidate_id=str(cmd.candidate_id),
            group_id=str(group_id),
        )
        return group_id

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
    "classify_join_error",
    "parse_invite_hash",
    "select_join_action",
]
