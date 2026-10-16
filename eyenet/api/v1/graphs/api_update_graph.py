# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/graphs/{graph_id} - rename / re-describe a saved graph."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.graphs._access import owned_graph_or_404
from eyenet.api.v1.schemas.saved_graphs import GraphSummary, UpdateGraphRequest
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graphs"])


@router.patch(
    "/graphs/{graph_id}",
    operation_id="graphs_update",
    response_model=GraphSummary,
    status_code=200,
)
async def graphs_update(
    graph_id: UUID,
    body: UpdateGraphRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> GraphSummary:
    await owned_graph_or_404(storage, current_user, graph_id)
    ok = await storage.update_investigation_graph(
        graph_id,
        name=body.name,
        description=body.description,
        now=datetime.now(tz=UTC),
    )
    if not ok:  # pragma: no cover - ownership check just confirmed existence
        raise ResourceNotFound("graph")
    row = await storage.get_investigation_graph(graph_id)
    if row is None:  # pragma: no cover - existence just confirmed
        raise ResourceNotFound("graph")
    return GraphSummary.from_domain(row)
