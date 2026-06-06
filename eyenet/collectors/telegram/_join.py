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

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import CandidateState, GroupKind, IdentityState, JoinedVia
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


# Unambiguous ban signal — the scout is no longer usable in this group.
_BAN_ERRORS = frozenset({"UserBannedInChannelError"})
# Refusals / transient failures: the candidate fails, the scout survives.
_FAIL_ERRORS = frozenset(
    {
        "FloodWaitError",
        "InviteHashExpiredError",
        "InviteHashInvalidError",
        "InviteRequestSentError",
        "ChannelPrivateError",
        "ChatWriteForbiddenError",
        "ChannelsTooMuchError",
        "UsernameInvalidError",
        "UsernameNotOccupiedError",
    }
)


def classify_join_error(exc_name: str) -> JoinOutcome:
    """Map a telethon exception *class name* to a :class:`JoinOutcome`.

    Switches on ``type(exc).__name__`` (a plain string) so this stays import-free
    and testable without telethon installed. Unknown errors default to
    ``FAILED`` — a join we couldn't complete, but not a confirmed ban (we do not
    burn a scout on an error we don't understand)."""
    if exc_name in _BAN_ERRORS:
        return JoinOutcome.BANNED
    return JoinOutcome.FAILED


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


__all__ = ["CollectorJoinHandler", "JoinOutcome", "classify_join_error"]
