# SPDX-License-Identifier: AGPL-3.0-or-later
"""InvestigationGraphTable + InvestigationGraphNodeTable — saved exploration graphs.

A saved canvas: a named set of node placements. Operator-drawn edges are NOT stored
here — they live in the global ``asserted_edge`` store and render between whichever
on-canvas nodes they connect. So a saved graph persists only which entities are on
the canvas, where (x/y), whether pinned, and which enrichments have been run on each.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import JSON, Field, SQLModel

from ._base import new_uuid7


class InvestigationGraphTable(SQLModel, table=True):
    __tablename__ = "investigation_graph"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    name: str = Field(max_length=256, index=True)
    description: str | None = Field(default=None, max_length=8192)
    created_by_user_id: UUID = Field(index=True)
    created_at: datetime
    updated_at: datetime


class InvestigationGraphNodeTable(SQLModel, table=True):
    __tablename__ = "investigation_graph_node"
    __table_args__ = (
        UniqueConstraint(
            "graph_id", "entity_type", "entity_id", name="uq_investigation_graph_node"
        ),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    graph_id: UUID = Field(foreign_key="investigation_graph.id", index=True)
    entity_type: str = Field(index=True)
    entity_id: UUID = Field(index=True)
    x: float
    y: float
    pinned: bool = False
    # Enrichment slugs already run on this node (so a reloaded canvas knows what has
    # been expanded). Open list, no schema coupling to the enrichment catalog.
    enrichments_run: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    added_at: datetime


__all__ = ["InvestigationGraphNodeTable", "InvestigationGraphTable"]
