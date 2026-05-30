# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors/{actor_id}/neighbors — typed graph neighbors (M9.F1)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.actors import (
    BelongsToPersonaEdge,
    LinkedToEdge,
    NeighborList,
)
from eyenet.models.graph import GraphEdgeTable, GraphEdgeType
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}/neighbors",
    operation_id="actors_neighbors",
    response_model=NeighborList,
    status_code=200,
)
async def actors_neighbors(
    actor_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> NeighborList:
    if await storage.get_actor(actor_id) is None:
        raise ResourceNotFound("actor")
    edges = cast(
        "list[GraphEdgeTable]",
        await storage.graph_neighbor_edges(actor_id, limit=page.fetch_limit, offset=page.offset),
    )
    items: list[LinkedToEdge | BelongsToPersonaEdge] = []
    for edge in edges[: page.limit]:
        if edge.edge_type is GraphEdgeType.LINKED_TO:
            items.append(LinkedToEdge.from_domain(edge))
        elif edge.edge_type is GraphEdgeType.BELONGS_TO_PERSONA:
            items.append(BelongsToPersonaEdge.from_domain(edge))
        # MEMBER_OF and any future edge types are not part of the neighbor
        # typed-union surface; skip them silently.
    estimated_total = await storage.count_graph_neighbors(actor_id) if page.include_total else None
    return NeighborList(
        items=items,
        next_cursor=page.next_cursor(fetched=len(edges)),
        estimated_total=estimated_total,
    )
