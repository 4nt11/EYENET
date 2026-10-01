"""ThreadSummaryTable — per-forum-thread rollup anchored on the OP (first post).

For a forum leak thread the important context lives in the OP (the dump announcement:
target, domain, country), not the replies. This sidecar anchors each FORUM_THREAD to
its OP and caches what the thread list needs to sort and filter without opening the
thread: the OP's post time (the real thread date) and its victim-country verdict.

Additive sidecar (mirrors message_geo): a new table create_all adds with no wipe.
``victim_country`` is cached because it is deterministic on the OP text (stable). The
OP's incident LABELS are NOT stored here — they change on reclassify/relabel, so the
thread list joins them live via ``op_message_id``. See eyenet/classifier/geo and
eyenet/services/geo_attribution.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class ThreadSummaryTable(SQLModel, table=True):
    __tablename__ = "thread_summary"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    group_id: UUID = Field(foreign_key="group_.id", index=True, unique=True)
    op_message_id: UUID = Field(foreign_key="message.id", index=True)
    op_sent_at: datetime = Field(index=True)  # the thread date (OP post time) — sort key
    victim_country: str | None = None  # ISO 3166-1 alpha-2; NULL when mixed/unknown
    victim_status: str  # "resolved" | "mixed" | "unknown"
    engine_version: str = Field(index=True)
    computed_at: datetime
