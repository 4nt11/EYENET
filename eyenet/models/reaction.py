"""ReactionTable — one row per reaction event.

Operator-grade evidence: one row per reaction event preserves the full
audit chain. Aggregation (count by emoji) is computed at query time, not
mutated in place. Redactions (`m.room.redaction` on Matrix, equivalent on
other platforms) set `redacted_at` rather than deleting the row.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class ReactionTable(SQLModel, table=True):
    __tablename__ = "reaction"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    message_id: UUID = Field(foreign_key="message.id", index=True)
    actor_id: UUID = Field(foreign_key="actor.id", index=True)
    emoji: str
    reacted_at: datetime
    evidence_ref: str = Field(index=True, unique=True)
    redacted_at: datetime | None = None


__all__ = ["ReactionTable"]
