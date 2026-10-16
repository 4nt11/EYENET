"""ActorTable + ActorAliasHistoryTable — see contracts/actor.py."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import ActorAliasKind

from ._base import new_uuid7


class ActorTable(SQLModel, table=True):
    __tablename__ = "actor"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    actor_key: str = Field(index=True, unique=True)
    source_id: UUID = Field(foreign_key="source.id", index=True)
    platform_userid: str = Field(index=True)
    current_handle: str | None = Field(default=None, index=True)
    current_display_name: str | None = None
    first_seen_at_source: datetime | None = None
    first_seen_at_ingest: datetime
    last_seen_at_source: datetime | None = None
    last_seen_at_ingest: datetime = Field(index=True)
    is_bot_self_declared: bool = False
    notes: str | None = None
    # Operator free-text assessment (write:actors). Analyst-authored dossier
    # note; distinct from `notes` (system/collector provenance).
    operator_assessment: str | None = None
    # "collected" (default; from a collector) vs "operator_asserted" (hand-created
    # on the exploration canvas). Open varchar, no DB enum. See OperatorEntitiesMixin.
    provenance: str = Field(default="collected", index=True)


class ActorAliasHistoryTable(SQLModel, table=True):
    __tablename__ = "actor_alias_history"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    actor_id: UUID = Field(foreign_key="actor.id", index=True)
    kind: ActorAliasKind
    value: str = Field(index=True)
    observed_from: datetime
    observed_until: datetime | None = None


__all__ = ["ActorAliasHistoryTable", "ActorTable"]
