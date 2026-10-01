# SPDX-License-Identifier: AGPL-3.0-or-later
"""ForumThreadAliasTable — map a thread's canonical tid to its stable group key.

DarkForums thread URLs are mostly tid-less SEO slugs (~83% carry no ``--<tid>``),
so a thread keyed by its slug is orphaned when the board RE-SLUGS it on a move
(e.g. ``Thread-DATABASE-UTEC-...`` -> ``Thread-UTEC-...`` when sent to "Removed
Content"). The thread PAGE, however, always exposes the canonical numeric tid
(reply links, ``input[name=tid]``), and that tid is stable across moves.

Rather than RE-KEY existing rows (which would change every message's
``evidence_ref`` -> ``forum:<board>:<tid>:<pid>`` and duplicate the thread on
re-poll), this table records, per source, the FIRST-seen group key for a tid.
Every poll resolves through it: the first copy of a thread binds
``tid -> its group key``; a later moved/re-slugged copy with the same tid resolves
to that same key, so its posts ingest into the original thread. Non-destructive:
existing rows and evidence_refs are never touched. Additive table (own Alembic
revision, 0003).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel, UniqueConstraint

from ._base import new_uuid7


class ForumThreadAliasTable(SQLModel, table=True):
    __tablename__ = "forum_thread_alias"
    __table_args__ = (UniqueConstraint("source_id", "canonical_tid", name="uq_forum_thread_alias"),)

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    source_id: UUID = Field(index=True)
    canonical_tid: str = Field(index=True)  # the board's stable numeric thread id
    platform_groupid: str  # the group key this tid resolves to (first-seen wins)
    first_seen_at: datetime
