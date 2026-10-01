# SPDX-License-Identifier: AGPL-3.0-or-later
"""ForumCrawlCursorTable — persistent per-category backfill progress.

The category sweep walks pages 1..N under a throttle, so a full pass takes many
hours. Without a persisted cursor every restart (or scheduled re-sweep) starts
at page 1 again and re-pays the throttle to re-fetch already-stored top pages
before it reaches the frontier. This table records how far the backfill got so a
restart RESUMES instead of re-scraping.

One row per (source, category). ``next_page`` is the page to resume the backfill
at; ``backfill_complete`` latches once the last page was reached. Deliberately
NOT reset on completion: once the archive is compiled we only track page 1
(newest, MyBB last-post-desc) from then on. To re-backfill, reset the row by
hand. Additive table, picked up by create_all with no wipe.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel, UniqueConstraint

from ._base import new_uuid7


class ForumCrawlCursorTable(SQLModel, table=True):
    __tablename__ = "forum_crawl_cursor"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "category_platform_groupid",
            name="uq_forum_crawl_cursor",
        ),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(index=True)
    category_platform_groupid: str = Field(index=True)  # the Forum-<name> slug
    next_page: int = Field(default=1)  # resume the backfill here; 1 = from the top
    backfill_complete: bool = Field(default=False)  # latched once last page reached
    updated_at: datetime
