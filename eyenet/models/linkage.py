"""LinkageTable — see contracts/attribution.py.

CHECK (actor_a_id < actor_b_id) is the dedup invariant (PLAN §5.2). Combined
with a unique index on (actor_a_id, actor_b_id, method) so the same proposed
linkage per method cannot appear as duplicate rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import LinkageState

from ._base import new_uuid7


class LinkageTable(SQLModel, table=True):
    __tablename__ = "linkage"
    __table_args__ = (
        CheckConstraint("actor_a_id < actor_b_id", name="linkage_pair_ordered"),
        UniqueConstraint("actor_a_id", "actor_b_id", "method", name="uq_linkage_pair_method"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # Cross-store references (actor lives in messages.db) — indexed UUID, no FK.
    actor_a_id: UUID = Field(index=True)
    actor_b_id: UUID = Field(index=True)
    state: LinkageState = Field(default=LinkageState.PROPOSED, index=True)
    method: str
    score: float
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    proposed_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    notes: str | None = None


__all__ = ["LinkageTable"]
