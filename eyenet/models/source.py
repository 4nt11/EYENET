"""SourceTable — see contracts/source.py."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import SourceKind

from ._base import new_uuid7


class SourceTable(SQLModel, table=True):
    __tablename__ = "source"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    kind: SourceKind = Field(index=True)
    display_name: str
    base_url: str | None = None
    created_at: datetime
    notes: str | None = None


__all__ = ["SourceTable"]
