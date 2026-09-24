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
from eyenet.contracts.enums import CandidateState
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["groups"])

# Candidate states from which an operator join can start.
_JOINABLE_FROM = frozenset(
    {CandidateState.DISCOVERED, CandidateState.QUEUED, CandidateState.PARKED}
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
