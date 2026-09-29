# SPDX-License-Identifier: AGPL-3.0-or-later
"""ForumMixin — operator-queued forum reply-to-unlock requests.

Generic SQLModel only (no dialect leak): the collector polls its source's PENDING
requests, executes each write under its own throttle, then marks the outcome.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select

from eyenet.contracts.enums import GroupKind
from eyenet.models import (
    ForumBackfillRequestTable,
    ForumReplyRequestTable,
    ForumThreadLinkTable,
    GroupTable,
    MessageTable,
)

from ._helpers import safe_session


class ForumMixin:
    async def record_forum_thread_link(
        self,
        *,
        source_id: UUID,
        category_platform_groupid: str,
        thread_platform_groupid: str,
        seen_at: datetime,
    ) -> None:
        """Record (idempotently) that a thread was discovered under a category."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = await session.exec(
                select(ForumThreadLinkTable)
                .where(ForumThreadLinkTable.source_id == source_id)
                .where(
                    col(ForumThreadLinkTable.category_platform_groupid) == category_platform_groupid
                )
                .where(col(ForumThreadLinkTable.thread_platform_groupid) == thread_platform_groupid)
            )
            row = existing.first()
            if row is not None:
                row.last_seen_at = seen_at
                session.add(row)
            else:
                session.add(
                    ForumThreadLinkTable(
                        source_id=source_id,
                        category_platform_groupid=category_platform_groupid,
                        thread_platform_groupid=thread_platform_groupid,
                        last_seen_at=seen_at,
                    )
                )
            await session.commit()

    async def list_threads_for_category(
        self,
        *,
        source_id: UUID,
        category_platform_groupid: str,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """FORUM_THREAD groups discovered under a category, most-recent-first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(GroupTable)
                .join(
                    ForumThreadLinkTable,
                    col(ForumThreadLinkTable.thread_platform_groupid)
                    == col(GroupTable.platform_groupid),
                )
                .where(col(ForumThreadLinkTable.source_id) == source_id)
                .where(
                    col(ForumThreadLinkTable.category_platform_groupid) == category_platform_groupid
                )
                .where(col(GroupTable.source_id) == source_id)
                .where(col(GroupTable.kind) == GroupKind.FORUM_THREAD)
                .order_by(col(GroupTable.last_observed_at_ingest).desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return list(result)

    def _category_search_stmt(
        self, projection: Any, *, source_id: UUID, category_platform_groupid: str, q: str
    ) -> Any:
        """Shared FROM/JOIN/WHERE for the category-level body search: message → its
        FORUM_THREAD group → the category link, filtered by the body match. The caller
        owns the projection (rows vs COUNT), ordering, limit and offset — so the page
        and its estimated_total can never diverge."""
        return (
            projection.join(GroupTable, col(MessageTable.group_id) == col(GroupTable.id))
            .join(
                ForumThreadLinkTable,
                col(ForumThreadLinkTable.thread_platform_groupid)
                == col(GroupTable.platform_groupid),
            )
            .where(col(ForumThreadLinkTable.source_id) == source_id)
            .where(col(ForumThreadLinkTable.category_platform_groupid) == category_platform_groupid)
            .where(col(GroupTable.source_id) == source_id)
            .where(col(GroupTable.kind) == GroupKind.FORUM_THREAD)
            .where(self._body_match(q))  # type: ignore[attr-defined]
        )

    async def search_messages_in_category(
        self,
        *,
        source_id: UUID,
        category_platform_groupid: str,
        q: str,
        limit: int,
        offset: int = 0,
    ) -> list[tuple[object, UUID, str | None]]:
        """Body-search across EVERY FORUM_THREAD under a category (the reader's
        category-level search), so an operator can find a post without opening each
        thread. Returns (MessageTable, thread_group_id, thread_title), newest match
        first. FTS5 on SQLite via the ``_body_match`` seam, LIKE elsewhere."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._category_search_stmt(
                select(MessageTable, GroupTable.id, GroupTable.current_title),
                source_id=source_id,
                category_platform_groupid=category_platform_groupid,
                q=q,
            )
            stmt = stmt.order_by(col(MessageTable.sent_at_source).desc()).limit(limit).offset(offset)
            result = await session.exec(stmt)
            return [(m, UUID(str(gid)), title) for m, gid, title in result.all()]

    async def count_messages_in_category(
        self, *, source_id: UUID, category_platform_groupid: str, q: str
    ) -> int:
        """Total matches for :meth:`search_messages_in_category` (no offset/limit) —
        the category search's ``estimated_total``."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = self._category_search_stmt(
                select(func.count()).select_from(MessageTable),
                source_id=source_id,
                category_platform_groupid=category_platform_groupid,
                q=q,
            )
            result = await session.exec(stmt)
            return int(result.one())

    async def create_forum_reply_request(
        self,
        *,
        source_id: UUID,
        group_id: UUID,
        message: str,
        requested_by: str,
        requested_at: datetime,
    ) -> UUID:
        """Enqueue one operator reply. Returns the request id (state=pending)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = ForumReplyRequestTable(
                source_id=source_id,
                group_id=group_id,
                message=message,
                requested_by=requested_by,
                requested_at=requested_at,
            )
            session.add(row)
            await session.commit()
            return row.id

    async def list_pending_forum_reply_requests(self, source_id: UUID) -> list[object]:
        """PENDING reply requests for a source, oldest-first (the collector's queue)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(ForumReplyRequestTable)
                .where(ForumReplyRequestTable.source_id == source_id)
                .where(col(ForumReplyRequestTable.state) == "pending")
                .order_by(col(ForumReplyRequestTable.requested_at).asc())
            )
            result = await session.exec(stmt)
            return list(result)

    async def complete_forum_reply_request(
        self,
        request_id: UUID,
        *,
        state: str,
        result: str | None,
        completed_at: datetime,
    ) -> None:
        """Mark a reply request done|failed with a result note. No-op if gone."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(ForumReplyRequestTable, request_id)
            if row is None:
                return
            row.state = state
            row.result = result
            row.completed_at = completed_at
            session.add(row)
            await session.commit()

    async def create_forum_backfill_request(
        self,
        *,
        source_id: UUID,
        group_id: UUID,
        requested_by: str,
        requested_at: datetime,
    ) -> UUID:
        """Enqueue a deep-backfill of one thread. Returns the request id."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = ForumBackfillRequestTable(
                source_id=source_id,
                group_id=group_id,
                requested_by=requested_by,
                requested_at=requested_at,
            )
            session.add(row)
            await session.commit()
            return row.id

    async def list_pending_forum_backfill_requests(self, source_id: UUID) -> list[object]:
        """PENDING backfill requests for a source, oldest-first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(ForumBackfillRequestTable)
                .where(ForumBackfillRequestTable.source_id == source_id)
                .where(col(ForumBackfillRequestTable.state) == "pending")
                .order_by(col(ForumBackfillRequestTable.requested_at).asc())
            )
            result = await session.exec(stmt)
            return list(result)

    async def complete_forum_backfill_request(
        self,
        request_id: UUID,
        *,
        state: str,
        result: str | None,
        completed_at: datetime,
    ) -> None:
        """Mark a backfill request done|failed. No-op if gone."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(ForumBackfillRequestTable, request_id)
            if row is None:
                return
            row.state = state
            row.result = result
            row.completed_at = completed_at
            session.add(row)
            await session.commit()
