# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/groups/leave — stop monitoring a joined group.

Optimistic + symmetric with join: park the candidate (JOINED -> PARKED), close the
active membership(s), and publish a LeaveGroupCommand to each collector in the
group (which departs on the platform). Requires `write:groups`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_bus,
    get_storage,
)
from eyenet.api.v1.schemas.groups import GroupSummary, LeaveGroupRequest
from eyenet.contracts.bus import Bus
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import CandidateState
from eyenet.contracts.supervisor import LeaveGroupCommand, command_subject_for
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["groups"])


@router.post(
    "/groups/leave",
    operation_id="groups_leave",
    response_model=GroupSummary,
    status_code=202,
)
async def groups_leave(
    body: LeaveGroupRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:groups"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    bus: Annotated[Bus, Depends(get_bus)],
) -> GroupSummary:
    candidate = await storage.get_candidate(body.candidate_id)
    if candidate is None:
        raise ResourceNotFound("group")
    if candidate.state is not CandidateState.JOINED or candidate.resulting_group_id is None:
        raise ConflictError(f"group is {candidate.state.value}; only a monitored group can be left")

    group_id = candidate.resulting_group_id
    now = datetime.now(tz=UTC)
    cmd = LeaveGroupCommand(group_id=group_id, reason=body.reason)
    payload = cmd.model_dump_json().encode("utf-8")

    for membership in await storage.list_active_memberships(group_id=group_id):
        await storage.close_membership(
            collector_id=membership.collector_id,
            group_id=group_id,
            left_at=now,
            left_reason=body.reason,
        )
        collector = await storage.get_collector(membership.collector_id)
        if collector is None:
            continue
        identity = await storage.get_identity(collector.identity_id)
        if identity is None:
            continue
        instance_id = compute_instance_id(identity.name, collector.kind)
        await bus.publish(
            command_subject_for(instance_id), payload, headers={"command-kind": cmd.kind}
        )

    row = await storage.transition_candidate(
        candidate_id=body.candidate_id,
        to_state=CandidateState.PARKED,
        reviewed_by=f"operator:{current_user.user_id}",
        reviewed_at=now,
    )
    await audit.emit(
        event="eyenet.audit.group.left",
        subject_kind="candidate",
        subject_id=body.candidate_id,
        system_user_id=current_user.user_id,
        payload={"group_id": str(group_id), "reason": body.reason},
    )
    return GroupSummary.from_domain(row)
