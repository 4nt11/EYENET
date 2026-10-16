# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request/response schemas for saved exploration graphs (the picker).

A saved graph is a named set of node placements; operator edges live in the global
asserted-edge store, not here. Projections of InvestigationGraph(Node)Row.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema
from .pagination import CursorPage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eyenet.contracts.investigation_graph import (
        InvestigationGraphNodeRow,
        InvestigationGraphRow,
    )


class GraphSummary(ApiSchema):
    """List/summary projection of a saved graph."""

    id: UUID
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, row: InvestigationGraphRow) -> GraphSummary:
        return cls(
            id=row.id,
            name=row.name,
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class GraphNode(ApiSchema):
    """One node placement on a saved graph."""

    id: UUID
    entity_type: str
    entity_id: UUID
    x: float
    y: float
    pinned: bool
    enrichments_run: list[str]
    added_at: datetime

    @classmethod
    def from_domain(cls, row: InvestigationGraphNodeRow) -> GraphNode:
        return cls(
            id=row.id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            x=row.x,
            y=row.y,
            pinned=row.pinned,
            enrichments_run=row.enrichments_run,
            added_at=row.added_at,
        )


class GraphEdge(ApiSchema):
    """One canvas edge, saved with the graph (derived or asserted)."""

    src_id: UUID
    dst_id: UUID
    kind: str
    provenance: str | None = None
    edge_id: UUID | None = None


class GraphDetail(ApiSchema):
    """Full saved graph: summary fields plus its node placements and edges."""

    id: UUID
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime
    nodes: list[GraphNode]
    edges: list[GraphEdge] = Field(default_factory=list)

    @classmethod
    def from_domain(
        cls, row: InvestigationGraphRow, nodes: Sequence[InvestigationGraphNodeRow]
    ) -> GraphDetail:
        return cls(
            id=row.id,
            name=row.name,
            description=row.description,
            created_at=row.created_at,
            updated_at=row.updated_at,
            nodes=[GraphNode.from_domain(n) for n in nodes],
            edges=[GraphEdge.model_validate(e) for e in (row.edges or [])],
        )


class NodePlacementIn(ApiSchema):
    """One node placement in a save-the-canvas request."""

    entity_type: str = Field(min_length=1, max_length=32)
    entity_id: UUID
    x: float
    y: float
    pinned: bool = False
    enrichments_run: list[str] = Field(default_factory=list)


class CreateGraphRequest(ApiSchema):
    """Body of ``POST /v1/graphs``."""

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=8192)


class UpdateGraphRequest(ApiSchema):
    """Body of ``PATCH /v1/graphs/{graph_id}``. Only present fields are applied."""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=8192)


class ReplaceGraphNodesRequest(ApiSchema):
    """Body of ``PUT /v1/graphs/{graph_id}/nodes`` (save-the-canvas)."""

    nodes: list[NodePlacementIn]
    edges: list[GraphEdge] = Field(default_factory=list)


class CursorPageGraphSummary(CursorPage[GraphSummary]):
    """200 page response for ``GET /v1/graphs``."""


__all__ = [
    "CreateGraphRequest",
    "CursorPageGraphSummary",
    "GraphDetail",
    "GraphNode",
    "GraphSummary",
    "NodePlacementIn",
    "ReplaceGraphNodesRequest",
    "UpdateGraphRequest",
]
