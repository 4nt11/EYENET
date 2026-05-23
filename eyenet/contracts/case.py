"""`Case` — operator investigation grouping (MODELS §2.15, PLAN §5.1).

Drives hot/cold/archived tier transitions: when ALL `Case` rows referencing
an `actor_id` are `closed`, the actor's data becomes eligible for cold-tier
migration after the configured grace period.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import CaseState


class CaseRow(DbRowBase):
    """Persisted case (MODELS §2.15)."""

    name: str
    state: CaseState = CaseState.OPEN
    opened_at: datetime
    closed_at: datetime | None = None
    actor_ids: list[UUID] = Field(default_factory=list)
    group_ids: list[UUID] = Field(default_factory=list)
    notes: str = ""


__all__ = ["CaseRow"]
