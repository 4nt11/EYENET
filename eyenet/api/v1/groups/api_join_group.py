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
from eyenet.contracts.candidate import GroupCandidateRow
from eyenet.contracts.enums import CandidateState, GroupKind, JoinedVia
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["groups"])

# Candidate states from which an operator join can start.
_JOINABLE_FROM = frozenset(
    {CandidateState.DISCOVERED, CandidateState.QUEUED, CandidateState.PARKED}
)

# Canonical walk to JOINED, indexed by the current state. A forum category has
# no platform join, so we complete this synchronously instead of handing off to
# the supervisor.
_FORUM_WALK_FROM = {
    CandidateState.DISCOVERED: 0,
    CandidateState.QUEUED: 1,
    CandidateState.APPROVED: 2,
    CandidateState.JOINING: 3,
}
_FORUM_WALK = (
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
    if await storage.get_collector(body.collector_id) is None:
        raise RequestValidationError(
            [{"loc": ("body", "collector_id"), "msg": "collector not found", "type": "value_error"}]
        )

    row = await _resolve_target(storage, body)

    # Forum categories have NO platform join to perform: monitoring one is a
    # purely internal membership. Complete it synchronously and never route it
    # through the supervisor join dispatch (that machinery acts against the
    # platform, which for a covert read collector would be deanonymizing).
    if (row.kind_hint or body.kind) is GroupKind.FORUM_CATEGORY:
        return await _monitor_forum_category(storage, audit, current_user, row, body.collector_id)

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


async def _monitor_forum_category(
    storage: BaseRepository,
    audit: AuditEmitter,
    current_user: CurrentUser,
    row: GroupCandidateRow,
    collector_id: UUID,
) -> GroupSummary:
    """Open an internal membership for a forum category — no platform action.

    Idempotent: re-monitoring an already-JOINED category is a no-op. The
    membership is what scopes the collector's read-crawl; nothing here contacts
    the board.
    """
    now = datetime.now(tz=UTC)
    group_id = await storage.upsert_group(
        source_id=row.source_id,
        platform_groupid=row.platform_groupid,
        kind=GroupKind.FORUM_CATEGORY,
        title=row.display_name_hint,
        seen_at=now,
    )

    if row.state is not CandidateState.JOINED:
        start = _FORUM_WALK_FROM.get(row.state)
        if start is None:
            raise ConflictError(f"category is {row.state.value}; cannot monitor from here")
        for to_state in _FORUM_WALK[start:]:
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


async def _resolve_target(storage: BaseRepository, body: JoinGroupRequest) -> GroupCandidateRow:
    """Return the candidate to join — by id, or ensure-created from source+groupid."""
    if body.candidate_id is not None:
        row = await storage.get_candidate(body.candidate_id)
        if row is None:
            raise ResourceNotFound("group")
        return row
    if body.source_id is None or body.platform_groupid is None:  # validator-guaranteed; typed guard
        raise ResourceNotFound("group")
    return await storage.ensure_candidate(
        source_id=body.source_id,
        platform_groupid=body.platform_groupid,
        seen_at=datetime.now(tz=UTC),
        kind=body.kind,
    )
