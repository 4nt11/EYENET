# SPDX-License-Identifier: AGPL-3.0-or-later
"""ForumReplyRequestTable — an operator-queued reply to unlock a gated thread.

Some MyBB posts hide their payload behind a `[hide]` gate: the content is only
visible after you reply. Replying is a WRITE against the forum, so it is NEVER
automatic. The operator explicitly enqueues one request here (with the exact
message they typed); the running collector — the only thing holding the session —
executes it inside its own throttle, honors flood control, then re-fetches the
thread to capture the now-unlocked content. State walks pending -> done | failed.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class ForumReplyRequestTable(SQLModel, table=True):
    __tablename__ = "forum_reply_request"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(index=True)  # the forum source; the collector polls its own
    group_id: UUID = Field(index=True)  # the FORUM_THREAD group to reply in (tid via the group)
    message: str  # the operator's typed reply, verbatim — never auto-generated
    state: str = Field(default="pending", index=True)  # pending | done | failed
    requested_by: str  # operator user id
    requested_at: datetime
    completed_at: datetime | None = None
    result: str | None = None  # success note or failure reason (flood, error, ...)
