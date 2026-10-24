# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/graph/expand — one enrichment hop for the exploration canvas.

Given a source node (``type`` + ``id``) and an ``enrichment``, return that node's
neighbours along the relation, cursor-paginated. Nodes reuse the search-graph
shape (hydrated from ``search_document``); the source node is not repeated.
See ``development/GRAPH_EXPLORER.md`` §6.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ScopeForbidden,
    UnprocessableError,
    get_storage,
)
from eyenet.api.deps_paging import CursorParams, cursor_params, encode_cursor
from eyenet.api.v1._clearance import enforce_entity_tier_clearance, required_clearance_scope
from eyenet.api.v1.schemas.enums import EntityType
from eyenet.api.v1.schemas.search import GraphExpandResult, SearchGraphEdge, SearchGraphNode
from eyenet.contracts.enums import SensitivityTier
from eyenet.enrichments.base import ExpandNode
from eyenet.enrichments.registry import REGISTRY, discover
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graph"])


def _cleared_for(fields: dict[str, Any] | None, current_user: CurrentUser) -> bool:
    """True if the caller may see a neighbour of this node's effective tier.

    Untiered nodes (no ``fields.tier``) always pass. An unknown tier string fails
    closed (treated as not cleared) rather than leaking.
    """
    raw = (fields or {}).get("tier")
    if not raw:
        return True
    try:
        needed = required_clearance_scope(SensitivityTier(raw))
    except ValueError:
        return False  # unknown tier -> fail closed
    return needed is None or needed.value in current_user.effective_scopes


def _filter_cleared(
    rows: list[ExpandNode], edges: list[dict[str, Any]], current_user: CurrentUser
) -> tuple[list[ExpandNode], list[dict[str, Any]]]:
    """Drop over-clearance neighbour nodes and any edge touching a dropped node."""
    kept = [r for r in rows if _cleared_for(r.fields, current_user)]
    if len(kept) == len(rows):
        return rows, edges
    dropped_ids = {r.entity_id for r in rows} - {r.entity_id for r in kept}
    # Edges run source -> neighbour; the source is not in rows. Drop an edge only when it
    # touches a DROPPED neighbour; edges to surviving/untiered nodes stay.
    pruned = [e for e in edges if e["src_id"] not in dropped_ids and e["dst_id"] not in dropped_ids]
    return kept, pruned


@router.get(
    "/graph/expand",
    operation_id="graph_expand",
    response_model=GraphExpandResult,
    status_code=200,
)
async def graph_expand(
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    node_type: Annotated[
        str, Query(alias="type", min_length=1, max_length=32, description="source entity_type")
    ],
    node_id: Annotated[UUID, Query(alias="id", description="source entity_id")],
    enrichment: Annotated[str, Query(min_length=1, max_length=48)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> GraphExpandResult:
    await enforce_entity_tier_clearance(storage, current_user, node_type, node_id)
    # Per-enrichment scope gate: an enrichment must not surface via the graph what the
    # caller couldn't read directly — each carries the read scope of its output domain
    # (read:actors, read:observations, …), and the creds enrichments require read:stealer.
    # Unknown (src_type, enrichment) is left to graph_expand's 422.
    discover()
    enr = REGISTRY.get((node_type, enrichment))
    if enr is not None and enr.effective_scope and (
        enr.effective_scope not in current_user.effective_scopes
    ):
        raise ScopeForbidden(enr.effective_scope)
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
    # Per-node clearance: enrichments that synthesize tier-gated neighbours (attachments,
    # future documents) stamp fields.tier. The src gate above only covers the source, so
    # drop over-clearance neighbours here and prune edges that reference the dropped ones.
    # (An entity with no fields.tier is untiered and always passes.)
    rows, edges = _filter_cleared(rows, edges, current_user)
    nodes = [
        SearchGraphNode(
            entity_type=EntityType(r.entity_type),
            entity_id=r.entity_id,
            title=r.title or "",
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
