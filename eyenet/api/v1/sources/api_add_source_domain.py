# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/sources/{source_id}/domains — add a SourceDomain (M9.D1).

Overlap is rejected with 409 (via the app's ``SourceDomainOverlapError``
handler). The ``?force=true`` overlap-bypass (§4.13, mark-both-ambiguous) needs
storage support the bridge resolver doesn't expose yet — deferred; every add
is overlap-checked here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.schemas.sources import AddSourceDomainRequest, SourceDomainView
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["sources"])


@router.post(
    "/sources/{source_id}/domains",
    operation_id="sources_add_domain",
    response_model=SourceDomainView,
    status_code=201,
)
async def sources_add_domain(
    source_id: UUID,
    body: AddSourceDomainRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> SourceDomainView:
    if cast("SourceRow | None", await storage.get_source(source_id)) is None:
        raise ResourceNotFound("source")
    # May raise SourceDomainOverlapError → 409 (app handler).
    row = await storage.add_source_domain(
        source_id=source_id,
        pattern=body.pattern,
        pattern_kind=body.pattern_kind,
        is_primary=body.is_primary,
        created_at=datetime.now(tz=UTC),
        created_by_user_id=current_user.user_id,
        notes=body.notes,
    )
    await audit.emit(
        event="eyenet.audit.source_domain.added",
        subject_kind="source",
        subject_id=source_id,
        system_user_id=current_user.user_id,
        payload={
            "domain_id": str(row.id),
            "pattern": row.pattern,
            "pattern_kind": row.pattern_kind.value,
            "is_primary": row.is_primary,
        },
    )
    return SourceDomainView.from_domain(row)
