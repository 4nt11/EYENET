# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/graphs/{graph_id} - delete a saved graph and its node placements."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.graphs._access import owned_graph_or_404
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graphs"])


@router.delete("/graphs/{graph_id}", operation_id="graphs_delete", status_code=204)
async def graphs_delete(
    graph_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> None:
    await owned_graph_or_404(storage, current_user, graph_id)
    if not await storage.delete_investigation_graph(graph_id):  # pragma: no cover - just confirmed
        raise ResourceNotFound("graph")
