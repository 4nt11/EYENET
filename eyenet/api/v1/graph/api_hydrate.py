# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/graph/hydrate — batch-resolve entity ids to graph nodes.

Given a set of entity ids (e.g. a saved graph's node refs), return the
``search_document`` node for each, so the exploration canvas can restore labels
and fields on load. Unindexed ids (documents are not search-indexed) are simply
absent from the response, so this never surfaces an unindexed entity's content.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.enums import EntityType
from eyenet.api.v1.schemas.search import (
    GraphHydrateRequest,
    GraphHydrateResult,
    SearchGraphNode,
)
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graph"])


@router.post(
    "/graph/hydrate",
    operation_id="graph_hydrate",
    response_model=GraphHydrateResult,
    status_code=200,
)
async def graph_hydrate(
    body: GraphHydrateRequest,
    _: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> GraphHydrateResult:
    rows = await storage.hydrate_search_documents(body.ids)
    nodes = [
        SearchGraphNode(
            entity_type=EntityType(r.entity_type),
            entity_id=r.entity_id,
            title=r.title,
            status=r.status,
            source_id=r.source_id,
            fields=r.fields or {},
        )
        for r in rows
    ]
    return GraphHydrateResult(nodes=nodes)
