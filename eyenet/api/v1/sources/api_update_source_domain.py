# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/sources/{source_id}/domains/{domain_id} — primary swap (M9.D1).

``pattern`` / ``pattern_kind`` are immutable post-create. ``is_primary: true``
promotes this domain to the source's primary (demoting the prior one in the
same transaction). Notes editing is deferred (remove + re-add).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.schemas.sources import SourceDomainView, UpdateSourceDomainRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["sources"])


@router.patch(
    "/sources/{source_id}/domains/{domain_id}",
    operation_id="sources_update_domain",
    response_model=SourceDomainView,
    status_code=200,
)
async def sources_update_domain(
    source_id: UUID,
    domain_id: UUID,
    body: UpdateSourceDomainRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> SourceDomainView:
    # Resolve against the active set so a removed/foreign domain is a clean 404.
    active = {d.id: d for d in await storage.list_source_domains(source_id=source_id)}
    current = active.get(domain_id)
    if current is None:
        raise ResourceNotFound("source_domain")

    if body.is_primary:
        current = await storage.swap_source_domain_primary(source_id=source_id, domain_id=domain_id)
        await audit.emit(
            event="eyenet.audit.source_domain.primary_swapped",
            subject_kind="source",
            subject_id=source_id,
            system_user_id=current_user.user_id,
            payload={"domain_id": str(domain_id), "pattern": current.pattern},
        )
    return SourceDomainView.from_domain(current)
