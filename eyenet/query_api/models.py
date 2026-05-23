"""Pydantic response models for the read-only query API.

Separate from the bus contracts — query-shape only. No SUBJECT constants.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict


class ActorSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: UUID
    role_signal: str | None = None
    role_confidence: float = 0.0
    profile_version: int | None = None
    derived_at: datetime | None = None
    persona_id: UUID | None = None


class NeighborEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    neighbor_id: UUID
    edge_type: str
    attrs: dict[str, object]


class PersonaSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: UUID
    member_count: int
    member_actors: list[ActorSummary]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LinkageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    linkage_id: UUID
    actor_a_id: UUID
    actor_b_id: UUID
    state: str
    method: str
    score: float
    proposed_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class GraphStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actors: int
    personas: int
    linked_to_edges: int
    belongs_to_persona_edges: int


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True


__all__ = [
    "ActorSummary",
    "GraphStats",
    "HealthResponse",
    "LinkageSummary",
    "NeighborEdge",
    "PersonaSummary",
]
