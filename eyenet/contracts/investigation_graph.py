# SPDX-License-Identifier: AGPL-3.0-or-later
"""`InvestigationGraph` + `InvestigationGraphNode` contracts — saved canvases.

Surface: db. See eyenet/models/investigation_graph.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase


class InvestigationGraphRow(DbRowBase):
    """Persisted saved-graph row (name + ownership + timestamps + canvas edges)."""

    name: str
    description: str | None = None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    edges: list[dict[str, Any]] = Field(default_factory=list)


class InvestigationGraphNodeRow(DbRowBase):
    """One node placement on a saved graph."""

    graph_id: UUID
    entity_type: str
    entity_id: UUID
    x: float
    y: float
    pinned: bool = False
    enrichments_run: list[str] = Field(default_factory=list)
    added_at: datetime
