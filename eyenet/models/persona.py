"""PersonaTable + PersonaMembershipTable.

Per MODELS §2.6a: `Persona.member_actor_ids` is the cheap forward view;
`PersonaMembership` is the indexed reverse view. An actor belongs to AT MOST
one persona at a time → unique index on `actor_id` alone in PersonaMembership.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

from ._base import new_uuid7


class PersonaTable(SQLModel, table=True):
    __tablename__ = "persona"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    label: str | None = None
    member_actor_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime
    updated_at: datetime


class PersonaMembershipTable(SQLModel, table=True):
    __tablename__ = "persona_membership"

    persona_id: UUID = Field(foreign_key="persona.id", primary_key=True)
    # Cross-store reference (actor lives in messages.db) — indexed UUID, no FK.
    actor_id: UUID = Field(primary_key=True, unique=True)
    joined_at: datetime
    # Audit reference — which linkage caused this membership. Not a hard FK
    # because the linkage row may be superseded; the membership outlives it.
    via_linkage_id: UUID | None = Field(default=None, index=True)


__all__ = ["PersonaMembershipTable", "PersonaTable"]
