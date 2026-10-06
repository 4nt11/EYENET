# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/graph/edges — map a durable operator edge (GLOBAL_SEARCH.md §10.4).

A mapped edge is operator-grade evidence: it persists as an ``asserted_edge`` row
and is audited. "Same person" belongs to the linkage lifecycle, not here.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.cases._detail import audit_ctx
from eyenet.api.v1.schemas.search import AssertEdgeRequest, AssertEdgeResult
from eyenet.models.asserted_edge import AssertedEdgeTable
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["graph"])


@router.post(
    "/graph/edges",
    operation_id="graph_assert_edge",
    response_model=AssertEdgeResult,
    status_code=200,
)
async def graph_assert_edge(
    body: AssertEdgeRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> AssertEdgeResult:
    edge = cast(
        "AssertedEdgeTable",
        await storage.assert_edge(
            src_type=body.src_type.value,
            src_id=body.src_id,
            dst_type=body.dst_type.value,
            dst_id=body.dst_id,
            kind=body.kind,
            reason=body.reason,
            created_by_user_id=current_user.user_id,
            **audit_ctx(audit),
        ),
    )
    return AssertEdgeResult(edge_id=edge.id, src_id=edge.src_id, dst_id=edge.dst_id, kind=edge.kind)
