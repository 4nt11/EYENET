"""Global-search schemas — one hit per entity + a faceted cursor page.

GLOBAL_SEARCH.md §4. A `SearchHit` is a thin projection of `SearchDocumentTable`
(the derived index), NOT the canonical entity; the UI links each hit to its
real detail surface by `entity_type` + `entity_id`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from eyenet.models.search import SearchDocumentTable

from ._base import ApiSchema
from .enums import EntityType
from .pagination import CursorPage


class SearchHit(ApiSchema):
    """One cross-entity search result row."""

    entity_type: EntityType
    entity_id: UUID
    source_id: UUID | None = None
    status: str | None = Field(
        default=None,
        description="Lifecycle facet within a type (group: candidate/joined/monitored/known).",
    )
    kind: str | None = Field(
        default=None,
        description="Sub-type facet within a type (artifact: wallet_btc/pgp_key/email/...).",
    )
    title: str
    subtitle: str | None = None
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured per-entity fields (author, timestamp, aliases, kind, ...) "
        "for configurable result columns.",
    )

    @classmethod
    def from_domain(cls, doc: SearchDocumentTable) -> SearchHit:
        return cls(
            entity_type=EntityType(doc.entity_type),
            entity_id=doc.entity_id,
            source_id=doc.source_id,
            status=doc.status,
            kind=doc.kind,
            title=doc.title,
            subtitle=doc.subtitle,
            fields=doc.fields or {},
        )


class CursorPageSearchHit(CursorPage[SearchHit]):
    """A page of hits plus facet counts for the whole matching set."""

    by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Count of matches per entity_type across the whole result set.",
    )
    by_source: dict[str, int] = Field(
        default_factory=dict,
        description="Count of matches per source_id ('' = no single source).",
    )
    by_kind: dict[str, int] = Field(
        default_factory=dict,
        description="Count of matches per sub-type kind (artifact InfrastructureKind); "
        "entities with no kind are omitted.",
    )
    source_labels: dict[str, str] = Field(
        default_factory=dict,
        description="Human display name per source_id (e.g. 'forum:darkforums-1'); "
        "for rendering rows/facets instead of the raw UUID.",
    )


class SearchGraphNode(ApiSchema):
    """One node in the induced subgraph (a search hit)."""

    entity_type: EntityType
    entity_id: UUID
    title: str
    status: str | None = None
    source_id: UUID | None = None
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured per-entity fields (same bag as the table hit) so the "
        "graph inspector shows full detail — author, timestamp, full message body, ...",
    )


class SearchGraphEdge(ApiSchema):
    """One edge in the induced subgraph. ``provenance`` = derived | asserted."""

    src_id: UUID
    dst_id: UUID
    kind: str
    weight: float | None = None
    provenance: str
    edge_id: UUID | None = Field(default=None, description="asserted_edge id (asserted only)")
    reason: str | None = None


class SearchGraph(ApiSchema):
    """The induced subgraph for a query: hits as nodes, their relations as edges."""

    nodes: list[SearchGraphNode] = Field(default_factory=list)
    edges: list[SearchGraphEdge] = Field(default_factory=list)
    source_labels: dict[str, str] = Field(default_factory=dict)


class AssertEdgeRequest(ApiSchema):
    """Map an operator edge between two entities (GLOBAL_SEARCH.md §10.4)."""

    src_type: EntityType
    src_id: UUID
    dst_type: EntityType
    dst_id: UUID
    kind: str = Field(
        min_length=1, max_length=64, description="associate | communicates_with | same_crew | ..."
    )
    reason: str = Field(min_length=3, max_length=1024)


class AssertEdgeResult(ApiSchema):
    edge_id: UUID
    src_id: UUID
    dst_id: UUID
    kind: str


class GraphExpandResult(ApiSchema):
    """One hop of the exploration canvas: the source node's neighbours along one
    enrichment, plus the derived edges connecting them. The source node is not
    repeated (the caller already has it); nodes reuse the search-graph shape."""

    enrichment: str
    nodes: list[SearchGraphNode] = Field(default_factory=list)
    edges: list[SearchGraphEdge] = Field(default_factory=list)
    next_cursor: str | None = None
    estimated_total: int | None = None


class GraphExpandCounts(ApiSchema):
    """Per-enrichment neighbour totals for a node (the degree preview). A value is
    ``None`` when the enrichment is available but has no cheap count (remote)."""

    counts: dict[str, int | None] = Field(default_factory=dict)


class GraphHydrateRequest(ApiSchema):
    """Body of ``POST /v1/graph/hydrate``: entity ids to look up (e.g. a saved
    graph's node refs, to restore labels/fields on load)."""

    ids: list[UUID] = Field(default_factory=list, max_length=500)


class GraphHydrateResult(ApiSchema):
    """Hydrated nodes for the requested ids. Unindexed ids (e.g. documents) are
    simply absent from ``nodes``."""

    nodes: list[SearchGraphNode] = Field(default_factory=list)


__all__ = [
    "AssertEdgeRequest",
    "AssertEdgeResult",
    "CursorPageSearchHit",
    "GraphExpandCounts",
    "GraphExpandResult",
    "SearchGraph",
    "SearchGraphEdge",
    "SearchGraphNode",
    "SearchHit",
]
