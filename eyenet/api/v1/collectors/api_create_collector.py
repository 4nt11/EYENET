# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/collectors — create a collector (M9.D2).

Leases an Identity (one collector per Identity). A reused identity or
duplicate instance_name surfaces as 409 via the app's IntegrityError handler.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.schemas.collectors import CollectorDetail, CreateCollectorRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["collectors"])


@router.post(
    "/collectors",
    operation_id="collectors_create",
    response_model=CollectorDetail,
    status_code=201,
)
async def collectors_create(
    body: CreateCollectorRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CollectorDetail:
    # May raise IntegrityError (identity reuse / instance_name collision) → 409.
    row = await storage.create_collector(
        instance_name=body.instance_name,
        kind=body.kind,
        source_id=body.source_id,
        identity_id=body.identity_id,
        config=body.config,
        created_at=datetime.now(tz=UTC),
        created_by_user_id=current_user.user_id,
        notes=body.notes,
    )
    await audit.emit(
        event="eyenet.audit.collector.created",
        subject_kind="collector",
        subject_id=row.id,
        system_user_id=current_user.user_id,
        payload={
            "instance_name": row.instance_name,
            "kind": row.kind.value,
            "source_id": str(row.source_id),
            "identity_id": str(row.identity_id),
        },
    )
    has_config_grant = "read:collectors_config" in current_user.effective_scopes
    return CollectorDetail.from_domain_detail(row, has_config_grant=has_config_grant)
