"""InfrastructureArtifactTable + ActorArtifactTable."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import InfrastructureKind

from ._base import new_uuid7


class InfrastructureArtifactTable(SQLModel, table=True):
    __tablename__ = "infrastructure_artifact"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    kind: InfrastructureKind = Field(index=True)
    value: str
    value_hash: str = Field(index=True)
    first_seen_at_ingest: datetime
    last_seen_at_ingest: datetime


class ActorArtifactTable(SQLModel, table=True):
    __tablename__ = "actor_artifact"

    actor_id: UUID = Field(foreign_key="actor.id", primary_key=True)
    artifact_id: UUID = Field(foreign_key="infrastructure_artifact.id", primary_key=True)
    first_seen_evidence_ref: str
    confidence: float


__all__ = ["ActorArtifactTable", "InfrastructureArtifactTable"]
