# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/graph/expand — one enrichment hop for the exploration canvas.

Given a source node (``type`` + ``id``) and an ``enrichment``, return that node's
neighbours along the relation, cursor-paginated. Nodes reuse the search-graph
shape (hydrated from ``search_document``); the source node is not repeated.
See ``development/GRAPH_EXPLORER.md`` §6.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, UnprocessableError, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params, encode_cursor
from eyenet.api.v1.schemas.enums import EntityType
from eyenet.api.v1.schemas.search import GraphExpandResult, SearchGraphEdge, SearchGraphNode
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graph"])


@router.get(
    "/graph/expand",
    operation_id="graph_expand",
    response_model=GraphExpandResult,
    status_code=200,
)
async def graph_expand(
    _: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    node_type: Annotated[
        str, Query(alias="type", min_length=1, max_length=32, description="source entity_type")
    ],
    node_id: Annotated[UUID, Query(alias="id", description="source entity_id")],
    enrichment: Annotated[str, Query(min_length=1, max_length=48)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> GraphExpandResult:
    try:
        rows, edges, total, has_more = await storage.graph_expand(
            src_type=node_type,
            src_id=node_id,
            enrichment=enrichment,
            limit=page.limit,
            offset=page.offset,
            want_total=page.include_total,
        )
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
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
    wire_edges = [
        SearchGraphEdge(
            src_id=e["src_id"], dst_id=e["dst_id"], kind=e["kind"], provenance="derived"
        )
        for e in edges
    ]
    return GraphExpandResult(
        enrichment=enrichment,
        nodes=nodes,
        edges=wire_edges,
        next_cursor=encode_cursor(page.offset + page.limit) if has_more else None,
        estimated_total=total,
    )
