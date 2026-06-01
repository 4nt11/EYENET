# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/sources/{source_id}/domains/{domain_id} — soft-remove (M9.D1).

Soft-delete only (sets ``removed_at``; the row is retained for audit and the
pattern is re-addable). The ``?hard=true`` full-drop (§4.13, admin:sources) has
no storage path yet — deferred.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["sources"])


@router.delete(
    "/sources/{source_id}/domains/{domain_id}",
    operation_id="sources_remove_domain",
    status_code=204,
)
async def sources_remove_domain(
    source_id: UUID,
    domain_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> Response:
    # Resolve against the active set so an already-removed/foreign domain 404s.
    active = {d.id for d in await storage.list_source_domains(source_id=source_id)}
    if domain_id not in active:
        raise ResourceNotFound("source_domain")
    await storage.remove_source_domain(
        domain_id=domain_id,
        removed_at=datetime.now(tz=UTC),
        removed_by_user_id=current_user.user_id,
    )
    await audit.emit(
        event="eyenet.audit.source_domain.removed",
        subject_kind="source",
        subject_id=source_id,
        system_user_id=current_user.user_id,
        payload={"domain_id": str(domain_id)},
    )
    return Response(status_code=204)
