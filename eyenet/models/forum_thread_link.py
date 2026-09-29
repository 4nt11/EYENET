# SPDX-License-Identifier: AGPL-3.0-or-later
"""ForumThreadLinkTable — which category a discovered forum thread lives under.

GroupTable has no parent pointer and adding a column would force a schema wipe,
so the category->thread edge lives here (additive table, picked up by create_all
with no wipe). Keyed by platform ids so the collector can record it at discovery
time without waiting for the thread's group row. Powers the reader's navigation:
category -> its threads.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel, UniqueConstraint

from ._base import new_uuid7


class ForumThreadLinkTable(SQLModel, table=True):
    __tablename__ = "forum_thread_link"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "category_platform_groupid",
            "thread_platform_groupid",
            name="uq_forum_thread_link",
        ),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(index=True)
    category_platform_groupid: str = Field(index=True)  # the Forum-<name> slug
    thread_platform_groupid: str = Field(index=True)  # the thread tid
    last_seen_at: datetime
