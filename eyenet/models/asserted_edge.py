# SPDX-License-Identifier: AGPL-3.0-or-later
"""AssertedEdgeTable — operator-mapped relationships (GLOBAL_SEARCH.md §10.4).

When an analyst draws an edge on the search graph it becomes a DURABLE,
audited row here: operator-grade evidence, not a derived view. Distinct from the
GraphService's derived ``graph_edge`` rows (recomputed from linkages/personas),
so a recompute can NEVER clobber an operator assertion. Soft-deleted (``removed_at``)
rather than hard-deleted — evidence is retained.

Endpoints are the same person's own: "same person" assertions flow through the
``linkage`` lifecycle, NOT here; this table is for associative relations linkage
does not model (associate / communicates-with / same-crew / ...).

``src_type``/``dst_type`` are plain strings (EntityType values), deliberately not
SQLAlchemy Enum columns (no native PG enum, no VARCHAR-length coupling).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class AssertedEdgeTable(SQLModel, table=True):
    __tablename__ = "asserted_edge"
    __table_args__ = (
        Index("ix_asserted_edge_src", "src_type", "src_id"),
        Index("ix_asserted_edge_dst", "dst_type", "dst_id"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    src_type: str
    src_id: UUID = Field(index=True)
    dst_type: str
    dst_id: UUID = Field(index=True)
    # Operator-chosen relation label (associate / communicates_with / same_crew / ...).
    kind: str
    reason: str
    created_by_user_id: UUID = Field(index=True)
    created_at: datetime
    # Soft-delete: retract without destroying the evidence trail.
    removed_at: datetime | None = Field(default=None, index=True)
    removed_by_user_id: UUID | None = None
    removal_reason: str | None = None


__all__ = ["AssertedEdgeTable"]
