# SPDX-License-Identifier: AGPL-3.0-or-later
"""ForumBackfillRequestTable — operator-queued deep backfill of a forum thread or
category page range.

Sweeps stay shallow for breadth. When a specific thread is worth its deep pages,
the operator queues a THREAD backfill (``from_page``/``to_page`` null); the
collector fetches all pages of that thread. When a fresh leak sank past the
steady window, the operator queues a CATEGORY backfill for an explicit page
RANGE (``from_page``..``to_page``). Read-only against the board (no write),
state walks pending -> done | failed.
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
    group_id: UUID = Field(index=True)  # FORUM_THREAD (deep-fetch) or FORUM_CATEGORY (page range)
    # Category page range (null for a thread backfill, which walks all pages).
    from_page: int | None = None
    to_page: int | None = None
    state: str = Field(default="pending", index=True)  # pending | done | failed
    requested_by: str
    requested_at: datetime
    completed_at: datetime | None = None
    result: str | None = None
