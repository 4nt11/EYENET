# SPDX-License-Identifier: AGPL-3.0-or-later
"""ForumBackfillRequestTable — operator-queued deep backfill of one forum thread.

Sweeps stay shallow (page 1: the leak + the OP) for breadth. When a specific
thread is worth its deep pages, the operator queues a backfill here; the running
collector fetches ALL pages of that thread under its throttle and ingests them.
Read-only against the board (no write), state walks pending -> done | failed.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class ForumBackfillRequestTable(SQLModel, table=True):
    __tablename__ = "forum_backfill_request"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(index=True)
    group_id: UUID = Field(index=True)  # the FORUM_THREAD group to deep-fetch
    state: str = Field(default="pending", index=True)  # pending | done | failed
    requested_by: str
    requested_at: datetime
    completed_at: datetime | None = None
    result: str | None = None
