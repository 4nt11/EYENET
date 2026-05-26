"""CollectorGroupMembership + MessageObservation contracts (MODELS §2.22-2.23, M9.C5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ._base import DbRowBase
from .enums import JoinedVia


class CollectorGroupMembershipRow(DbRowBase):
    """Persisted CollectorGroupMembership row (MODELS §2.22).

    ``left_at`` is None for active memberships. Rows are retained for audit
    on departure — re-joining produces a new row with a fresh ``id``.
    """

    collector_id: UUID
    group_id: UUID
    joined_at: datetime
    joined_via: JoinedVia
    joined_via_candidate_id: UUID | None = None
    left_at: datetime | None = None
    left_reason: str | None = Field(default=None, max_length=64)


class MessageObservationRow(BaseModel):
    """Persisted MessageObservation row (MODELS §2.23).

    Composite identity (message_id, collector_id) — no UUID PK on the table,
    so this contract does NOT extend DbRowBase.

    ``was_first_sighting`` is True iff this collector's record_observation
    call was the first for this ``message_id``. Sensor primitives run only on
    first-sighting to avoid double-counting; secondary observations are the
    dual-cover insurance record.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    collector_id: UUID
    observed_at_ingest: datetime
    was_first_sighting: bool


__all__ = [
    "CollectorGroupMembershipRow",
    "MessageObservationRow",
]
