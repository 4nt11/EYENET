# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/collectors/{collector_id}/stop — request STOPPED (M9.D2).

Sugar for ``PATCH {desired_state: STOPPED}``. 202 (supervisor reconciles).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.schemas.collectors import CollectorDetail
from eyenet.contracts.enums import CollectorDesiredState
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["collectors"])


@router.post(
    "/collectors/{collector_id}/stop",
    operation_id="collectors_stop",
    response_model=CollectorDetail,
    status_code=202,
)
async def collectors_stop(
    collector_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CollectorDetail:
    if await storage.get_collector(collector_id) is None:
        raise ResourceNotFound("collector")
    row = await storage.set_collector_desired_state(
        collector_id=collector_id, desired_state=CollectorDesiredState.STOPPED
    )
    await audit.emit(
        event="eyenet.audit.collector.stop_requested",
        subject_kind="collector",
        subject_id=collector_id,
        system_user_id=current_user.user_id,
        payload={"desired_state": CollectorDesiredState.STOPPED.value},
    )
    has_config_grant = "read:collectors_config" in current_user.effective_scopes
    return CollectorDetail.from_domain_detail(row, has_config_grant=has_config_grant)
