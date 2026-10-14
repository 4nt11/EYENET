"""InfrastructureArtifactTable + ActorArtifactTable (MODELS §2.7-2.8, §2.25)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import InfrastructureKind, ResolutionState

from ._base import new_uuid7


class InfrastructureArtifactTable(SQLModel, table=True):
    """`infrastructure_artifact` — extracted artifacts (MODELS §2.7).

    The bridge-resolution fields (``resolved_to_source_id``,
    ``resolution_state``) are set inline by ``ArtifactsMixin`` per the §2.25
    invariant — never by an async job, never by an operator-triggered tool.
    """

    __tablename__ = "infrastructure_artifact"
    __table_args__ = (
        CheckConstraint(
            "resolution_state IN ('UNRESOLVED','RESOLVED','AMBIGUOUS','NOT_APPLICABLE')",
            name="ck_artifact_resolution_state",
        ),
        # If resolved, the FK MUST be populated; otherwise it MUST be NULL.
        CheckConstraint(
            "(resolution_state = 'RESOLVED' AND resolved_to_source_id IS NOT NULL) "
            "OR (resolution_state != 'RESOLVED' AND resolved_to_source_id IS NULL)",
            name="ck_artifact_resolved_fk_paired",
        ),
        Index("ix_artifact_resolved_source", "resolved_to_source_id"),
        Index("ix_artifact_resolution_state", "resolution_state"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    kind: InfrastructureKind = Field(index=True)
    value: str
    value_hash: str = Field(index=True)
    first_seen_at_ingest: datetime
    last_seen_at_ingest: datetime
    # §2.25 — populated inline by Path A on artifact insert; updated inline
    # by Path B on SourceDomain insert.
    resolved_to_source_id: UUID | None = Field(default=None, foreign_key="source.id")
    resolution_state: ResolutionState = Field(default=ResolutionState.UNRESOLVED)


class ActorArtifactTable(SQLModel, table=True):
    __tablename__ = "actor_artifact"

    actor_id: UUID = Field(foreign_key="actor.id", primary_key=True)
    artifact_id: UUID = Field(foreign_key="infrastructure_artifact.id", primary_key=True)
    first_seen_evidence_ref: str
    confidence: float


class InfrastructureArtifactMentionTable(SQLModel, table=True):
    """`infrastructure_artifact_mention` — provenance edge: artifact seen in a message.

    One row per ``(artifact_id, message_id)``. The deduped artifact lives once in
    ``infrastructure_artifact``; this records every message it appeared in, so the
    actor, source, group, thread/template and timing are all reachable by joining
    ``message`` (MessageTable). Per-mention ``ts`` feeds the temporal linkage
    signals (cross-forum synchrony, burstiness) that need per-sighting timestamps,
    which the actor-level ``actor_artifact`` rollup cannot provide.
    """

    __tablename__ = "infrastructure_artifact_mention"
    __table_args__ = (
        UniqueConstraint("artifact_id", "message_id", name="uq_artifact_mention_edge"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    artifact_id: UUID = Field(foreign_key="infrastructure_artifact.id", index=True)
    message_id: UUID = Field(foreign_key="message.id", index=True)
    # Char offset of the match in the message body, when known.
    char_offset: int | None = None
    # When the artifact was mentioned (the message's ingest/source time).
    ts: datetime


__all__ = [
    "ActorArtifactTable",
    "InfrastructureArtifactMentionTable",
    "InfrastructureArtifactTable",
]
