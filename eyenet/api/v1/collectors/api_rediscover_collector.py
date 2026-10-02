# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/collectors/{collector_id}/rediscover — rescan ONE collector's board.

The per-collector twin of POST /v1/groups/scan (which fans out to every running
collector). Publishes a ScanVisibleGroupsCommand to just this collector's command
channel; it re-enumerates what its identity can see and upserts each as a
GroupCandidate. This is the explicit way to refresh discovery — automatic startup
discovery runs only ONCE per source. Requires write:groups.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_bus,
    get_storage,
)
from eyenet.api.v1.schemas.groups import ScanGroupsResult
from eyenet.contracts.bus import Bus
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import CollectorObservedState
from eyenet.contracts.supervisor import ScanVisibleGroupsCommand, command_subject_for
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["collectors"])


@router.post(
    "/collectors/{collector_id}/rediscover",
    operation_id="collectors_rediscover",
    response_model=ScanGroupsResult,
    status_code=202,
)
async def collectors_rediscover(
    collector_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:groups"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    bus: Annotated[Bus, Depends(get_bus)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> ScanGroupsResult:
    collector = await storage.get_collector(collector_id)
    if collector is None:
        raise ResourceNotFound("collector")

    # Only a RUNNING collector has a live command subscriber; a stopped one would
    # drop the command on the floor. Report 0 signaled so the UI can say "start it
    # first" rather than imply a scan is happening.
    signaled = 0
    if collector.observed_state is CollectorObservedState.RUNNING:
        identity = await storage.get_identity(collector.identity_id)
        if identity is not None:
            instance_id = compute_instance_id(identity.name, collector.kind)
            cmd = ScanVisibleGroupsCommand()
            await bus.publish(
                command_subject_for(instance_id),
                cmd.model_dump_json().encode("utf-8"),
                headers={"command-kind": cmd.kind},
            )
            signaled = 1

    await audit.emit(
        event="eyenet.audit.collector.rediscover_requested",
        subject_kind="collector",
        subject_id=collector_id,
        system_user_id=current_user.user_id,
        payload={"signaled": signaled},
    )
    return ScanGroupsResult(collectors_signaled=signaled)
