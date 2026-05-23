"""GraphNodeTable + GraphEdgeTable — SQLModel schemas for the graph store.

Node types: Actor, Persona, Group.
Edge types: LinkedTo (actor↔actor linkage), BelongsToPersona (actor∈persona),
            MemberOf (actor∈group from social_graph).

Graph backend decision (PLAN §11.1): SQLite-with-edges for v0 zero-ops.
Revisit at M5 if scale forces it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel

from ._base import new_uuid7


class GraphNodeType(StrEnum):
    ACTOR = "actor"
    PERSONA = "persona"
    GROUP = "group"


class GraphEdgeType(StrEnum):
    LINKED_TO = "linked_to"
    BELONGS_TO_PERSONA = "belongs_to_persona"
    MEMBER_OF = "member_of"


class GraphNodeTable(SQLModel, table=True):
    __tablename__ = "graph_node"
    __table_args__ = (Index("ix_graph_node_type", "node_type"),)

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    node_id: UUID = Field(index=True)
    node_type: GraphNodeType
    attrs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime


class GraphEdgeTable(SQLModel, table=True):
    __tablename__ = "graph_edge"
    __table_args__ = (
        Index("ix_graph_edge_src", "src_id"),
        Index("ix_graph_edge_dst", "dst_id"),
        Index("ix_graph_edge_type_src", "edge_type", "src_id"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    edge_type: GraphEdgeType
    src_id: UUID = Field(index=True)
    dst_id: UUID = Field(index=True)
    attrs: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime


__all__ = [
    "GraphEdgeTable",
    "GraphEdgeType",
    "GraphNodeTable",
    "GraphNodeType",
]
