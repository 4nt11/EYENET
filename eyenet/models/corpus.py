"""CorpusCursorTable — composite PK on (actor_id, primitive_name)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class CorpusCursorTable(SQLModel, table=True):
    __tablename__ = "corpus_cursor"

    # Cross-store reference (actor lives in messages.db) — UUID, no FK.
    actor_id: UUID = Field(primary_key=True)
    primitive_name: str = Field(primary_key=True)
    last_processed_msg_ts: datetime
    last_processed_msg_id: UUID


__all__ = ["CorpusCursorTable"]
