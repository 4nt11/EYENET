# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/groups/scan — refresh group visibility across running collectors.

Publishes a `ScanVisibleGroupsCommand` to each RUNNING collector's command
channel; the collector enumerates what its identity can see and upserts each as a
GroupCandidate. Source-agnostic (each collector implements enumeration for its
platform). Requires `write:groups`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_bus, get_storage
from eyenet.api.v1.schemas.groups import ScanGroupsResult
from eyenet.contracts.bus import Bus
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import CollectorObservedState
from eyenet.contracts.supervisor import ScanVisibleGroupsCommand, command_subject_for
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["groups"])


@router.post(
    "/groups/scan",
    operation_id="groups_scan",
    response_model=ScanGroupsResult,
    status_code=202,
)
async def groups_scan(
    _: Annotated[CurrentUser, Depends(RequireScope("write:groups"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    bus: Annotated[Bus, Depends(get_bus)],
) -> ScanGroupsResult:
    cmd = ScanVisibleGroupsCommand()
    payload = cmd.model_dump_json().encode("utf-8")
    signaled = 0
    for collector in await storage.list_collectors():
        if collector.observed_state is not CollectorObservedState.RUNNING:
            continue
        identity = await storage.get_identity(collector.identity_id)
        if identity is None:
            continue
        instance_id = compute_instance_id(identity.name, collector.kind)
        await bus.publish(
            command_subject_for(instance_id),
            payload,
            headers={"command-kind": cmd.kind},
        )
        signaled += 1
    return ScanGroupsResult(collectors_signaled=signaled)
