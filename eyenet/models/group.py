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
    # "collected" (default) vs "operator_asserted". Open varchar, no DB enum.
    provenance: str = Field(default="collected", index=True)
    # Reincarnation lineage: the external platform_groupid churns when a channel/board is
    # nuked-and-recreated, so each incarnation is a distinct row. ``lineage_id`` is the
    # stable logical-group key shared by every incarnation (== ``id`` for a root), and
    # ``group_iteration`` is the 1-based version within it. A plain indexed key, not a
    # DB FK, to keep the self-referential root (lineage_id == id) simple on insert.
    lineage_id: UUID | None = Field(default=None, index=True)
    group_iteration: int = Field(default=1)


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
