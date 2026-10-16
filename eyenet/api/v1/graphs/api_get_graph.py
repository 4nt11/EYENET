# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/graphs/{graph_id} - a saved graph with its node placements."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.graphs._access import owned_graph_or_404
from eyenet.api.v1.schemas.saved_graphs import GraphDetail
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graphs"])


@router.get(
    "/graphs/{graph_id}",
    operation_id="graphs_get",
    response_model=GraphDetail,
    status_code=200,
)
async def graphs_get(
    graph_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> GraphDetail:
    row = await owned_graph_or_404(storage, current_user, graph_id)
    nodes = await storage.get_investigation_graph_nodes(graph_id)
    return GraphDetail.from_domain(row, nodes)
