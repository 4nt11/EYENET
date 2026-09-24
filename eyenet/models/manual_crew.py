"""ManualCrewTable + ManualCrewMemberTable — operator-curated actor groups.

Distinct from the *derived* crews on /actor-groups (connected components of the
shared-infra graph, recomputed each request). A manual crew is hand-built by an
operator: named, persisted, and edited over time as members are added or removed.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class ManualCrewTable(SQLModel, table=True):
    __tablename__ = "manual_crew"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    name: str = Field(max_length=256, index=True)
    notes: str | None = None
    created_by: UUID = Field(foreign_key="system_user.id", index=True)
    created_at: datetime
    updated_at: datetime


class ManualCrewMemberTable(SQLModel, table=True):
    __tablename__ = "manual_crew_member"
    __table_args__ = (
        UniqueConstraint("crew_id", "actor_id", name="uq_manual_crew_member"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    crew_id: UUID = Field(foreign_key="manual_crew.id", index=True)
    actor_id: UUID = Field(foreign_key="actor.id", index=True)
    added_at: datetime


__all__ = ["ManualCrewMemberTable", "ManualCrewTable"]
