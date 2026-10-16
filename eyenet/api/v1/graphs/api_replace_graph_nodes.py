# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/graphs/{graph_id}/nodes - save the canvas (replace all node placements)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.graphs._access import owned_graph_or_404
from eyenet.api.v1.schemas.saved_graphs import GraphDetail, ReplaceGraphNodesRequest
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graphs"])


@router.put(
    "/graphs/{graph_id}/nodes",
    operation_id="graphs_replace_nodes",
    response_model=GraphDetail,
    status_code=200,
)
async def graphs_replace_nodes(
    graph_id: UUID,
    body: ReplaceGraphNodesRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> GraphDetail:
    await owned_graph_or_404(storage, current_user, graph_id)
    await storage.replace_investigation_graph_nodes(
        graph_id,
        [(n.entity_type, n.entity_id, n.x, n.y, n.pinned, n.enrichments_run) for n in body.nodes],
        edges=[e.model_dump(mode="json") for e in body.edges],
        now=datetime.now(tz=UTC),
    )
    row = await storage.get_investigation_graph(graph_id)
    if row is None:  # pragma: no cover - existence just confirmed
        raise ResourceNotFound("graph")
    nodes = await storage.get_investigation_graph_nodes(graph_id)
    return GraphDetail.from_domain(row, nodes)
