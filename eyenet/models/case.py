"""CaseTable — see contracts/case.py."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import CaseState

from ._base import new_uuid7


class CaseTable(SQLModel, table=True):
    __tablename__ = "case_"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    name: str = Field(index=True)
    state: CaseState = Field(default=CaseState.OPEN, index=True)
    opened_at: datetime
    closed_at: datetime | None = None
    actor_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    group_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    notes: str = ""


__all__ = ["CaseTable"]
