# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/graphs - create an empty saved exploration graph."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.saved_graphs import CreateGraphRequest, GraphSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graphs"])


@router.post(
    "/graphs",
    operation_id="graphs_create",
    response_model=GraphSummary,
    status_code=201,
)
async def graphs_create(
    body: CreateGraphRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> GraphSummary:
    graph_id = await storage.create_investigation_graph(
        name=body.name,
        description=body.description,
        created_by_user_id=current_user.user_id,
        now=datetime.now(tz=UTC),
    )
    row = await storage.get_investigation_graph(graph_id)
    if row is None:  # pragma: no cover - just created
        raise ResourceNotFound("graph")
    return GraphSummary.from_domain(row)
