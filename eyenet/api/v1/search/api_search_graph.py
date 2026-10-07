# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/search/graph — the induced subgraph for a query (GLOBAL_SEARCH.md §10.3).

Nodes are the search hits (capped); edges are the relations among them (derived:
linkage/actor_relation/shared-infra/persona) plus operator-asserted edges.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, UnprocessableError, get_storage
from eyenet.api.v1.schemas.search import SearchGraph, SearchGraphEdge, SearchGraphNode
from eyenet.models.asserted_edge import AssertedEdgeTable
from eyenet.models.search import SearchDocumentTable
from eyenet.storage.query import UnknownFieldError
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
    try:
        rows = cast(
            "list[SearchDocumentTable]",
            await storage.search_global(
                q, types=_csv(types), status=_csv(status), source_id=source, limit=limit, offset=0
            ),
        )
    except UnknownFieldError as exc:
        raise UnprocessableError(str(exc)) from exc
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

    # Thread/message -> attributed author: inject the author as a NODE (if not already
    # a hit) and spoke every thread (its OP author) and message (its sender) into it, so
    # author-owned content clusters on the real actor. Authors also join the actor set so
    # linkage/relation edges among authors show too.
    actor_ids = list(by_type.get("actor", []))
    authored: list[tuple[UUID, UUID]] = []  # (content_id, author_actor_id)

    def _inject(author_map: dict[UUID, tuple[UUID, str, UUID | None]]) -> None:
        for ent_id, (actor_id, handle, src_id) in author_map.items():
            if actor_id not in all_ids:
                nodes.append(
                    SearchGraphNode(
                        entity_type="actor",  # type: ignore[arg-type]
                        entity_id=actor_id,
                        title=handle,
                        status=None,
                        source_id=src_id,
                        fields={},
                    )
                )
                all_ids.add(actor_id)
                actor_ids.append(actor_id)
            authored.append((ent_id, actor_id))

    _inject(await storage.thread_op_authors(by_type.get("thread", [])))
    _inject(await storage.message_authors(by_type.get("message", [])))

    derived = await storage.induced_edges(
        actor_ids=actor_ids,
        persona_ids=by_type.get("persona", []),
        artifact_ids=by_type.get("artifact", []),
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
    for content_id, actor_id in authored:
        edges.append(
            SearchGraphEdge(
                src_id=content_id, dst_id=actor_id, kind="authored_by", provenance="derived"
            )
        )
    # same_handle: actors sharing an EXACT handle across sources are probably one account
    # (e.g. "LaPampaLeaks" on telegram + a forum). Derived hint, dashed — the operator
    # promotes it to a persona when confirmed; we never auto-assert identity.
    by_handle: dict[str, list[UUID]] = defaultdict(list)
    for n in nodes:
        if n.entity_type == "actor" and n.title:
            by_handle[n.title.strip().lower()].append(n.entity_id)
    for same in by_handle.values():
        uniq = list(dict.fromkeys(same))
        for a_id, b_id in combinations(uniq, 2):
            edges.append(
                SearchGraphEdge(src_id=a_id, dst_id=b_id, kind="same_handle", provenance="derived")
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
    for sid in {str(n.source_id) for n in nodes if n.source_id is not None}:
        srow = await storage.get_source(UUID(sid))
        if srow is not None:
            source_labels[sid] = getattr(srow, "display_name", sid)

    return SearchGraph(nodes=nodes, edges=edges, source_labels=source_labels)
