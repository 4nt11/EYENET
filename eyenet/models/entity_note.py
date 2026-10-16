# SPDX-License-Identifier: AGPL-3.0-or-later
"""EntityNoteTable — one operator note per graph entity.

The persistent backing for the exploration canvas's Notes tab (the mockup fakes it
in localStorage). One editable note per ``(entity_type, entity_id)`` — upsert, not a
log. Distinct from ``actor.operator_assessment`` (actor-only dossier field) and from
case ``observations``; this is a free-text note on ANY entity type.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class EntityNoteTable(SQLModel, table=True):
    __tablename__ = "entity_note"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", name="uq_entity_note"),)

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    entity_type: str = Field(index=True)
    entity_id: UUID = Field(index=True)
    body: str = Field(max_length=16384)
    created_by_user_id: UUID = Field(index=True)
    created_at: datetime
    updated_at: datetime


__all__ = ["EntityNoteTable"]
