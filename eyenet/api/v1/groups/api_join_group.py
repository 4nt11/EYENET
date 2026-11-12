# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/groups/join — operator-initiated "join at will".

Reuses the candidate machinery: ensure a `GroupCandidate` exists, walk it to
APPROVED (assigning the chosen collector), and let the supervisor execute the
join off-path — identical to approving a triaged candidate. Works for a group the
account is already in (the collector's join is idempotent) and for an undiscovered
group (a candidate is created first). Requires `write:groups`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.api.v1.schemas.groups import GroupSummary, JoinGroupRequest
from eyenet.collectors.telegram._join import parse_invite_hash
from eyenet.contracts.candidate import GroupCandidateRow
from eyenet.contracts.enums import (
    ArtifactSubjectKind,
    CandidateState,
    GroupAccessKind,
    GroupKind,
    JoinedVia,
    SourceKind,
)
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["groups"])

# Candidate states from which an operator join can start.
_JOINABLE_FROM = frozenset(
    {CandidateState.DISCOVERED, CandidateState.QUEUED, CandidateState.PARKED}
)

# Canonical walk to JOINED, indexed by the current state. A platform with no join
# to perform (forum category; a Discord channel we are already in via the guild)
# completes this synchronously instead of handing off to the supervisor.
_INTERNAL_WALK_FROM = {
    CandidateState.DISCOVERED: 0,
    CandidateState.QUEUED: 1,
    CandidateState.APPROVED: 2,
    CandidateState.JOINING: 3,
    # PARKED re-monitors via the existing PARKED -> APPROVED edge (walk from APPROVED).
    CandidateState.PARKED: 1,
}
_INTERNAL_WALK = (
    CandidateState.QUEUED,
    CandidateState.APPROVED,
    CandidateState.JOINING,
    CandidateState.JOINED,
)


@router.post(
    "/groups/join",
    operation_id="groups_join",
    response_model=GroupSummary,
    status_code=202,
)
async def groups_join(
    body: JoinGroupRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:groups"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> GroupSummary:
    collector = await storage.get_collector(body.collector_id)
    if collector is None:
        raise RequestValidationError(
            [{"loc": ("body", "collector_id"), "msg": "collector not found", "type": "value_error"}]
        )

    # Invite-link joins are a Telegram-only access vector (ImportChatInvite). Fail
    # loud rather than create a candidate no collector can act on.
    if body.invite_link is not None and collector.kind is not SourceKind.TELEGRAM:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "invite_link"),
                    "msg": "invite-link joins are Telegram-only",
                    "type": "value_error",
                }
            ]
        )

    row = await _resolve_target(storage, body, collector.source_id)

    # A collector only ever crawls its OWN source's board. Ensure-created targets
    # are keyed on the collector's source, so this only bites the candidate_id
    # path: joining a candidate that belongs to a different source produces an
    # inert cross-source membership (the slug is swept against the wrong board,
    # the bug that stranded a slug-colliding forum category). Fail loud instead.
    if collector.source_id != row.source_id:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "collector_id"),
                    "msg": (
                        f"collector belongs to source {collector.source_id}, "
                        f"not the group's source {row.source_id}"
                    ),
                    "type": "value_error",
                }
            ]
        )

    # Forum categories have NO platform join to perform: monitoring one is a
    # purely internal membership. Complete it synchronously and never route it
    # through the supervisor join dispatch (that machinery acts against the
    # platform, which for a covert read collector would be deanonymizing).
    if (row.kind_hint or body.kind) is GroupKind.FORUM_CATEGORY:
        return await _monitor_internal(
            storage, audit, current_user, row, body.collector_id, kind=GroupKind.FORUM_CATEGORY
        )

    # Discord is the same case: we are already in the guild, so monitoring a channel
    # (or the guild node) is a purely internal membership — there is no platform join
    # and the collector has no join-command handler to dispatch to.
    if collector.kind is SourceKind.DISCORD:
        return await _monitor_internal(
            storage, audit, current_user, row, body.collector_id,
            kind=(row.kind_hint or body.kind or GroupKind.CHANNEL),
        )

    # Walk to APPROVED (DISCOVERED -> QUEUED -> APPROVED); supervisor joins off-path.
    if row.state not in _JOINABLE_FROM:
        raise ConflictError(f"group is {row.state.value}; cannot start a join from here")
    if row.state is CandidateState.DISCOVERED:
        await storage.transition_candidate(candidate_id=row.id, to_state=CandidateState.QUEUED)
    try:
        await storage.transition_candidate(
            candidate_id=row.id,
            to_state=CandidateState.APPROVED,
            reviewed_by=f"operator:{current_user.user_id}",
            reviewed_at=datetime.now(tz=UTC),
            assigned_collector_id=body.collector_id,
            backfill_on_join=body.backfill,
        )
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc

    await audit.emit(
        event="eyenet.audit.group.join_requested",
        subject_kind="candidate",
        subject_id=row.id,
        system_user_id=current_user.user_id,
        payload={"collector_id": str(body.collector_id), "platform_groupid": row.platform_groupid},
    )
    final = await storage.get_candidate(row.id)
    if final is None:  # pragma: no cover — just transitioned
        raise ResourceNotFound("group")
    return GroupSummary.from_domain(final)


async def _monitor_internal(
    storage: BaseRepository,
    audit: AuditEmitter,
    current_user: CurrentUser,
    row: GroupCandidateRow,
    collector_id: UUID,
    *,
    kind: GroupKind,
) -> GroupSummary:
    """Open an internal membership for a group with no platform join to perform
    (forum category, Discord channel/guild) — no platform action.

    Idempotent: re-monitoring an already-JOINED group is a no-op. The membership
    is what scopes the collector's read-crawl; nothing here contacts the platform.
    """
    now = datetime.now(tz=UTC)
    group_id, _ = await storage.upsert_group(
        source_id=row.source_id,
        platform_groupid=row.platform_groupid,
        kind=kind,
        title=row.display_name_hint,
        seen_at=now,
    )

    if row.state is not CandidateState.JOINED:
        start = _INTERNAL_WALK_FROM.get(row.state)
        if start is None:
            raise ConflictError(f"group is {row.state.value}; cannot monitor from here")
        for to_state in _INTERNAL_WALK[start:]:
            kwargs: dict[str, object] = {}
            if to_state is CandidateState.APPROVED:
                kwargs = {
                    "reviewed_by": f"operator:{current_user.user_id}",
                    "reviewed_at": now,
                    "assigned_collector_id": collector_id,
                }
            elif to_state is CandidateState.JOINED:
                kwargs = {"resulting_group_id": group_id}
            await storage.transition_candidate(candidate_id=row.id, to_state=to_state, **kwargs)  # type: ignore[arg-type]

    # Idempotent membership: check-then-open, never swallow the duplicate error.
    if not await storage.list_active_memberships(collector_id=collector_id, group_id=group_id):
        await storage.open_membership(
            collector_id=collector_id,
            group_id=group_id,
            joined_at=now,
            joined_via=JoinedVia.CANDIDATE,
            joined_via_candidate_id=row.id,
        )

    await audit.emit(
        event="eyenet.audit.group.category_monitored",
        subject_kind="candidate",
        subject_id=row.id,
        system_user_id=current_user.user_id,
        payload={"collector_id": str(collector_id), "platform_groupid": row.platform_groupid},
    )
    final = await storage.get_candidate(row.id)
    if final is None:  # pragma: no cover - just transitioned
        raise ResourceNotFound("group")
    return GroupSummary.from_domain(final)


async def _resolve_target(
    storage: BaseRepository, body: JoinGroupRequest, collector_source_id: UUID
) -> GroupCandidateRow:
    """Return the candidate to join: an existing candidate by id, or one
    ensure-created for a public handle / invite link under the COLLECTOR's source
    (a collector only ever joins its own source's groups)."""
    if body.candidate_id is not None:
        row = await storage.get_candidate(body.candidate_id)
        if row is None:
            raise ResourceNotFound("group")
        return row
    if body.invite_link is not None:
        return await _ensure_invite_candidate(storage, body, collector_source_id)
    if body.platform_groupid is None:  # validator-guaranteed; typed guard
        raise ResourceNotFound("group")
    return await storage.ensure_candidate(
        source_id=collector_source_id,
        platform_groupid=body.platform_groupid,
        seen_at=datetime.now(tz=UTC),
        kind=body.kind,
    )


async def _ensure_invite_candidate(
    storage: BaseRepository, body: JoinGroupRequest, source_id: UUID
) -> GroupCandidateRow:
    """Ensure a candidate for a private invite link under ``source_id`` (the
    collector's source) and attach the invite as an access artifact, so the
    supervisor selects it and the collector joins via ImportChatInvite.

    The invite hash is not a stable group id, so the candidate is keyed on a
    synthetic ``joinchat:<hash>`` platform_groupid (the same shape the live join
    writes back). Idempotent: a re-submit of the same link reuses the candidate and
    does not pile up duplicate artifacts."""
    invite_hash = parse_invite_hash(body.invite_link)
    if invite_hash is None:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "invite_link"),
                    "msg": "not a Telegram invite link (expected t.me/+... or t.me/joinchat/...)",
                    "type": "value_error",
                }
            ]
        )
    now = datetime.now(tz=UTC)
    candidate = await storage.ensure_candidate(
        source_id=source_id,
        platform_groupid=f"joinchat:{invite_hash}",
        seen_at=now,
        kind=body.kind or GroupKind.CHANNEL,
    )
    existing = await storage.list_group_access_artifacts_for_candidate(candidate.id)
    if not any(
        a.kind is GroupAccessKind.INVITE_LINK and a.value == body.invite_link for a in existing
    ):
        await storage.add_group_access_artifact(
            subject_kind=ArtifactSubjectKind.CANDIDATE,
            group_id=None,
            candidate_id=candidate.id,
            kind=GroupAccessKind.INVITE_LINK,
            value=body.invite_link,
            discovered_at_ingest=now,
        )
    return candidate
