# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/graph/edges/{edge_id} — retract an operator-asserted edge (§10.4).

Soft-delete (evidence retained) + audited. 404 if the edge is absent or already
retracted.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.api.v1.cases._detail import audit_ctx
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["graph"])


@router.delete(
    "/graph/edges/{edge_id}",
    operation_id="graph_retract_edge",
    status_code=204,
)
async def graph_retract_edge(
    edge_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    reason: Annotated[str, Query(min_length=3, max_length=1024)],
) -> None:
    ok = await storage.retract_edge(
        edge_id=edge_id,
        removed_by_user_id=current_user.user_id,
        reason=reason,
        **audit_ctx(audit),
    )
    if not ok:
        raise ResourceNotFound("asserted_edge")
