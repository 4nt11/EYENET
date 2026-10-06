# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/search/graph — the induced subgraph for a query (GLOBAL_SEARCH.md §10.3).

Nodes are the search hits (capped); edges are the relations among them (derived:
linkage/actor_relation/shared-infra/persona) plus operator-asserted edges.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.search import SearchGraph, SearchGraphEdge, SearchGraphNode
from eyenet.models.asserted_edge import AssertedEdgeTable
from eyenet.models.search import SearchDocumentTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["search"])


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


@router.get(
    "/search/graph",
    operation_id="search_graph",
    response_model=SearchGraph,
    status_code=200,
)
async def search_graph(
    _: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    q: Annotated[str, Query(min_length=1, max_length=256)],
    types: Annotated[str | None, Query(description="CSV of entity types")] = None,
    status: Annotated[str | None, Query(description="CSV of status facets")] = None,
    source: Annotated[UUID | None, Query(description="Restrict to one source_id")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="node cap")] = 300,
) -> SearchGraph:
    rows = cast(
        "list[SearchDocumentTable]",
        await storage.search_global(
            q, types=_csv(types), status=_csv(status), source_id=source, limit=limit, offset=0
        ),
    )
    nodes = [
        SearchGraphNode(
            entity_type=r.entity_type,  # type: ignore[arg-type]
            entity_id=r.entity_id,
            title=r.title,
            status=r.status,
            source_id=r.source_id,
            fields=r.fields or {},
        )
        for r in rows
    ]
    by_type: dict[str, list[UUID]] = {}
    all_ids: set[UUID] = set()
    for r in rows:
        by_type.setdefault(r.entity_type, []).append(r.entity_id)
        all_ids.add(r.entity_id)

    edges: list[SearchGraphEdge] = []
    derived = await storage.induced_edges(
        actor_ids=by_type.get("actor", []),
        persona_ids=by_type.get("persona", []),
        artifact_ids=by_type.get("artifact", []),
        thread_ids=by_type.get("thread", []),
    )
    for e in derived:
        edges.append(
            SearchGraphEdge(
                src_id=e["src_id"],
                dst_id=e["dst_id"],
                kind=e["kind"],
                weight=e.get("weight"),
                provenance="derived",
            )
        )
    for ae in cast("list[AssertedEdgeTable]", await storage.list_asserted_edges_for(all_ids)):
        edges.append(
            SearchGraphEdge(
                src_id=ae.src_id,
                dst_id=ae.dst_id,
                kind=ae.kind,
                provenance="asserted",
                edge_id=ae.id,
                reason=ae.reason,
            )
        )

    source_labels: dict[str, str] = {}
    for sid in {str(r.source_id) for r in rows if r.source_id is not None}:
        srow = await storage.get_source(UUID(sid))
        if srow is not None:
            source_labels[sid] = getattr(srow, "display_name", sid)

    return SearchGraph(nodes=nodes, edges=edges, source_labels=source_labels)
