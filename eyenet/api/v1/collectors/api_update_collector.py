# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/collectors/{collector_id} — update editable fields (M9.D2).

``config`` / ``instance_name`` / ``notes`` via ``update_collector``;
``desired_state`` via ``set_collector_desired_state``. ``observed_state`` is
never settable here (supervisor-only). Only fields present are applied.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.schemas.collectors import CollectorDetail, UpdateCollectorRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["collectors"])


@router.patch(
    "/collectors/{collector_id}",
    operation_id="collectors_update",
    response_model=CollectorDetail,
    status_code=200,
)
async def collectors_update(
    collector_id: UUID,
    body: UpdateCollectorRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CollectorDetail:
    if await storage.get_collector(collector_id) is None:
        raise ResourceNotFound("collector")
    fields = body.model_fields_set
    if "config" in fields or "instance_name" in fields or "notes" in fields:
        await storage.update_collector(
            collector_id=collector_id,
            config=body.config if "config" in fields else None,
            instance_name=body.instance_name if "instance_name" in fields else None,
            notes=body.notes if "notes" in fields else None,
        )
    if "desired_state" in fields and body.desired_state is not None:
        await storage.set_collector_desired_state(
            collector_id=collector_id, desired_state=body.desired_state
        )

    await audit.emit(
        event="eyenet.audit.collector.updated",
        subject_kind="collector",
        subject_id=collector_id,
        system_user_id=current_user.user_id,
        payload={"fields": sorted(fields)},
    )
    row = await storage.get_collector(collector_id)
    if row is None:  # pragma: no cover — existence checked above
        raise ResourceNotFound("collector")
    has_config_grant = "read:collectors_config" in current_user.effective_scopes
    return CollectorDetail.from_domain_detail(row, has_config_grant=has_config_grant)
