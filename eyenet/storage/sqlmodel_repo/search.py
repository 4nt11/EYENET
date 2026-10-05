# SPDX-License-Identifier: AGPL-3.0-or-later
"""SearchMixin — global cross-entity search over `search_document` (GLOBAL_SEARCH.md).

Generic, dialect-free layer (Rule 1): the free-text predicate is ANSI
``LOWER(col) LIKE '%q%'`` via the ``_search_predicate`` seam, overridden on the
concrete backends with FTS (SQLite FTS5, Postgres ``tsvector`` + ``pg_trgm``).
Bulk upsert is SELECT-then-add here; the concrete backends override with an
atomic ``ON CONFLICT (entity_type, entity_id)``.

All methods run on the MAIN store (`self._session_factory`) — `search_document`
lives in `main.db` / `main`, like `message_fts`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, or_
from sqlmodel import col, select

from eyenet.models import SearchDocumentTable
from eyenet.models._base import now_utc

from ._helpers import safe_session

# Result ordering: lower rank shown first. Identity-ish entities outrank bulk
# content so an actor whose handle IS the query beats a message mentioning it.
# Relevance tuning (handle-vs-prose, bm25/ts_rank blending) is Phase 3.
_TYPE_RANK: dict[str, int] = {
    "actor": 0,
    "persona": 1,
    "crew": 2,
    "artifact": 3,
    "case": 4,
    "group": 5,
    "thread": 6,
    "document": 7,
    "mention": 8,
    "message": 9,
    "attachment": 10,
    "incident": 11,
}
_DEFAULT_RANK = 99

# Columns the indexer writes; used to coerce an upsert payload.
_COLUMNS = (
    "entity_type",
    "entity_id",
    "source_id",
    "status",
    "title",
    "subtitle",
    "haystack",
    "handles",
    "updated_at",
)


class SearchMixin:
    # ---- dialect seam -----------------------------------------------------
    def _search_predicate(self, q: str) -> Any:
        """Generic ANSI substring match over haystack + handles.

        Concrete backends override with FTS. Rule 1: no dialect SQL here.
        """
        pattern = f"%{q.lower()}%"
        return or_(
            func.lower(col(SearchDocumentTable.haystack)).like(pattern),
            func.lower(func.coalesce(col(SearchDocumentTable.handles), "")).like(pattern),
        )

    @staticmethod
    def _type_rank() -> Any:
        return case(_TYPE_RANK, value=col(SearchDocumentTable.entity_type), else_=_DEFAULT_RANK)

    @staticmethod
    def _apply_filters(
        stmt: Any,
        *,
        types: Sequence[str] | None,
        status: Sequence[str] | None,
        source_id: UUID | None,
    ) -> Any:
        if types:
            stmt = stmt.where(col(SearchDocumentTable.entity_type).in_(list(types)))
        if status:
            stmt = stmt.where(col(SearchDocumentTable.status).in_(list(status)))
        if source_id is not None:
            stmt = stmt.where(SearchDocumentTable.source_id == source_id)
        return stmt

    # ---- reads ------------------------------------------------------------
    async def search_global(
        self,
        q: str,
        *,
        types: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        source_id: UUID | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(SearchDocumentTable).where(self._search_predicate(q))
            stmt = self._apply_filters(stmt, types=types, status=status, source_id=source_id)
            stmt = (
                stmt.order_by(self._type_rank())
                .order_by(col(SearchDocumentTable.updated_at).desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return list(result)

    async def count_search_global(
        self,
        q: str,
        *,
        types: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        source_id: UUID | None = None,
    ) -> int:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(func.count())
                .select_from(SearchDocumentTable)
                .where(self._search_predicate(q))
            )
            stmt = self._apply_filters(stmt, types=types, status=status, source_id=source_id)
            result = await session.exec(stmt)
            return int(result.one())

    async def search_global_facets(
        self,
        q: str,
        *,
        types: Sequence[str] | None = None,
        status: Sequence[str] | None = None,
        source_id: UUID | None = None,
    ) -> dict[str, dict[str, int]]:
        """``{"by_type": {...}, "by_source": {...}}``.

        by_type ignores the ``types`` filter (so the UI shows every type's count
        to pivot into); by_source ignores the ``source_id`` filter likewise.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            # by_type: apply status + source, NOT types.
            t_stmt = (
                select(col(SearchDocumentTable.entity_type), func.count())
                .where(self._search_predicate(q))
                .group_by(col(SearchDocumentTable.entity_type))
            )
            t_stmt = self._apply_filters(t_stmt, types=None, status=status, source_id=source_id)
            by_type = {str(k): int(v) for k, v in (await session.exec(t_stmt)).all()}

            # by_source: apply types + status, NOT source.
            s_stmt = (
                select(col(SearchDocumentTable.source_id), func.count())
                .where(self._search_predicate(q))
                .group_by(col(SearchDocumentTable.source_id))
            )
            s_stmt = self._apply_filters(s_stmt, types=types, status=status, source_id=None)
            by_source = {
                (str(k) if k is not None else ""): int(v)
                for k, v in (await session.exec(s_stmt)).all()
            }
        return {"by_type": by_type, "by_source": by_source}

    # ---- writes (generic SELECT-then-add; backends override bulk) ----------
    @staticmethod
    def _coerce(fields: dict[str, Any]) -> dict[str, Any]:
        row = {k: fields.get(k) for k in _COLUMNS}
        if row.get("updated_at") is None:
            row["updated_at"] = now_utc()
        if row.get("title") is None:
            row["title"] = ""
        if row.get("haystack") is None:
            row["haystack"] = ""
        return row

    async def put_search_documents_bulk(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            for raw in rows:
                r = self._coerce(dict(raw))
                existing = (
                    await session.exec(
                        select(SearchDocumentTable).where(
                            SearchDocumentTable.entity_type == r["entity_type"],
                            SearchDocumentTable.entity_id == r["entity_id"],
                        )
                    )
                ).first()
                if existing is None:
                    session.add(SearchDocumentTable(**r))
                else:
                    for k, v in r.items():
                        setattr(existing, k, v)
                    session.add(existing)
            await session.commit()

    async def put_search_document(self, **fields: Any) -> None:
        await self.put_search_documents_bulk([fields])

    async def delete_search_document(self, entity_type: str, entity_id: UUID) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = (
                await session.exec(
                    select(SearchDocumentTable).where(
                        SearchDocumentTable.entity_type == entity_type,
                        SearchDocumentTable.entity_id == entity_id,
                    )
                )
            ).first()
            if existing is not None:
                await session.delete(existing)
                await session.commit()


__all__ = ["SearchMixin"]
