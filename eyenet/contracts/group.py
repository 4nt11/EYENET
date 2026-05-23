"""`Group` contract — chat / channel / forum thread / room (MODELS §1.3, §2.11).

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ._base import DbRowBase
from .enums import GroupKind


class GroupRow(DbRowBase):
    """Persisted Group row (MODELS §1.3)."""

    source_id: UUID
    platform_groupid: str
    kind: GroupKind
    current_title: str | None = None
    current_description: str | None = None
    is_public: bool | None = None
    member_count: int | None = None
    first_seen_at_ingest: datetime
    last_observed_at_ingest: datetime


class GroupSnapshotRow(DbRowBase):
    """Group state at an observation point (MODELS §2.11)."""

    group_id: UUID
    title: str | None = None
    description: str | None = None
    member_count: int | None = None
    is_public: bool | None = None
    observed_at: datetime


__all__ = ["GroupRow", "GroupSnapshotRow"]
