"""GroupTable + GroupSnapshotTable — see contracts/group.py."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import GroupKind

from ._base import new_uuid7


class GroupTable(SQLModel, table=True):
    __tablename__ = "group_"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(foreign_key="source.id", index=True)
    platform_groupid: str = Field(index=True)
    kind: GroupKind = Field(index=True)
    current_title: str | None = None
    current_description: str | None = None
    is_public: bool | None = None
    member_count: int | None = None
    first_seen_at_ingest: datetime
    last_observed_at_ingest: datetime


class GroupSnapshotTable(SQLModel, table=True):
    __tablename__ = "group_snapshot"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    group_id: UUID = Field(foreign_key="group_.id", index=True)
    title: str | None = None
    description: str | None = None
    member_count: int | None = None
    is_public: bool | None = None
    observed_at: datetime = Field(index=True)


__all__ = ["GroupSnapshotTable", "GroupTable"]
