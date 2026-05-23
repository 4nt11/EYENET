"""MembershipTable — Actor↔Group join (MODELS §2.2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import MembershipRole

from ._base import new_uuid7


class MembershipTable(SQLModel, table=True):
    __tablename__ = "membership"
    __table_args__ = (UniqueConstraint("actor_id", "group_id", name="uq_membership_actor_group"),)

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    actor_id: UUID = Field(foreign_key="actor.id", index=True)
    group_id: UUID = Field(foreign_key="group_.id", index=True)
    role: MembershipRole = Field(default=MembershipRole.UNKNOWN, index=True)
    joined_at_source: datetime | None = None
    joined_at_ingest: datetime
    left_at_ingest: datetime | None = None


__all__ = ["MembershipTable"]
