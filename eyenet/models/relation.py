"""ActorRelationTable — materialized directed actor-to-actor relationships.

One row per (from_actor, to_actor, kind) with an occurrence count and the source
time span. Built by :mod:`eyenet.relations.mentions` as a full-rebuild batch pass
(the API form of it lives at POST /v1/relations/rebuild), mirroring the anti-spam
linker passes. MENTION edges come from ``@handle`` tokens resolved against actor
handles; FORWARD edges from a relayed message's origin author.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import RelationKind

from ._base import new_uuid7


class ActorRelationTable(SQLModel, table=True):
    __tablename__ = "actor_relation"
    __table_args__ = (
        UniqueConstraint("from_actor_id", "to_actor_id", "kind", name="uq_actor_relation_edge"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(foreign_key="source.id", index=True)
    from_actor_id: UUID = Field(foreign_key="actor.id", index=True)
    to_actor_id: UUID = Field(foreign_key="actor.id", index=True)
    kind: RelationKind = Field(index=True)
    occurrence_count: int = 0
    first_seen_at_source: datetime
    last_seen_at_source: datetime


__all__ = ["ActorRelationTable"]
