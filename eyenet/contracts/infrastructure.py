"""Infrastructure artifacts and Actor↔Infrastructure join (MODELS §2.7, §2.8).

Wallets, PGP keys, domains, phone numbers, emails, cross-platform handles,
onion addresses. Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import InfrastructureKind


class InfrastructureArtifactRow(DbRowBase):
    """Persisted artifact (MODELS §2.7)."""

    kind: InfrastructureKind
    value: str = Field(description="normalized form")
    value_hash: str = Field(min_length=64, max_length=64, description="sha256(value)")
    first_seen_at_ingest: datetime
    last_seen_at_ingest: datetime


class ActorArtifactRow(DbRowBase):
    """Actor↔Artifact join (MODELS §2.8). Composite PK in SQLModel layer."""

    actor_id: UUID
    artifact_id: UUID
    first_seen_evidence_ref: str
    confidence: float = Field(ge=0.0, le=1.0)


__all__ = ["ActorArtifactRow", "InfrastructureArtifactRow"]
