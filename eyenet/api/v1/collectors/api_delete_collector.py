# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/collectors/{collector_id} — hard delete a stopped collector (M9.D2).

Refused (409) unless ``observed_state == STOPPED`` — never delete a live
collector out from under the supervisor. ``admin:collectors`` (grant-only).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.contracts.enums import CollectorObservedState
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["collectors"])


@router.delete(
    "/collectors/{collector_id}",
    operation_id="collectors_delete",
    status_code=204,
)
async def collectors_delete(
    collector_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> Response:
    row = await storage.get_collector(collector_id)
    if row is None:
        raise ResourceNotFound("collector")
    if row.observed_state is not CollectorObservedState.STOPPED:
        raise ConflictError(f"collector is {row.observed_state.value}; stop it before deletion")
    await storage.delete_collector(collector_id)
    await audit.emit(
        event="eyenet.audit.collector.deleted",
        subject_kind="collector",
        subject_id=collector_id,
        system_user_id=current_user.user_id,
        payload={"instance_name": row.instance_name},
    )
    return Response(status_code=204)
