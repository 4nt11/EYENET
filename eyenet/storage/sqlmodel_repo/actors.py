# SPDX-License-Identifier: AGPL-3.0-or-later
"""ActorsMixin — source / group / actor upsert + actor_key resolve."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_
from sqlmodel import col, select

from eyenet.contracts.actor import ActorRow
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.contracts.source import SourceRow
from eyenet.models import ActorTable, GroupTable, SourceTable

from ._helpers import safe_session


def _aware(dt: datetime) -> datetime:
    """Normalize a naive (SQLite-returned) datetime to UTC-aware."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _aware_opt(dt: datetime | None) -> datetime | None:
    return None if dt is None else _aware(dt)


def _row_to_actor(row: ActorTable) -> ActorRow:
    return ActorRow(
        id=row.id,
        actor_key=row.actor_key,
        source_id=row.source_id,
        platform_userid=row.platform_userid,
        current_handle=row.current_handle,
        current_display_name=row.current_display_name,
        first_seen_at_source=_aware_opt(row.first_seen_at_source),
        first_seen_at_ingest=_aware(row.first_seen_at_ingest),
        last_seen_at_source=_aware_opt(row.last_seen_at_source),
        last_seen_at_ingest=_aware(row.last_seen_at_ingest),
        is_bot_self_declared=row.is_bot_self_declared,
        notes=row.notes,
    )


def _row_to_source(row: SourceTable) -> SourceRow:
    return SourceRow(
        id=row.id,
        kind=row.kind,
        display_name=row.display_name,
        canonical_url=row.canonical_url,
        created_at=_aware(row.created_at),
        notes=row.notes,
    )


class ActorsMixin:
    async def resolve_actor_id(self, actor_key: str) -> UUID | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ActorTable).where(ActorTable.actor_key == actor_key))
            row = result.first()
            return row.id if row else None

    async def get_actor(self, actor_id: UUID) -> object | None:
        """Return the :class:`ActorRow` for a primary-key id, or None (M9.F1)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(ActorTable, actor_id)
            return _row_to_actor(row) if row is not None else None

    async def get_source(self, source_id: UUID) -> object | None:
        """Return the :class:`SourceRow` for a primary-key id, or None (M9.F1).

        Used by the actor-detail handler to project an actor's single platform.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(SourceTable, source_id)
            return _row_to_source(row) if row is not None else None

    async def count_actors(self) -> int:
        """Total number of actors (M9.F3 graph stats)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(func.count()).select_from(ActorTable))
            return int(result.one())

    def _actor_search_clause(self, q: str) -> ColumnElement[bool]:
        """Case-insensitive substring match on handle / display name (M9.F3).

        ANSI ``LOWER(col) LIKE '%q%'`` — portable across backends, no FTS5
        dependency. Per CLAUDE.md §2.3 Rule 1 this stays dialect-free; a
        future SQLite FTS5 override can supersede it if ranking is needed.
        """
        pattern = f"%{q.lower()}%"
        return or_(
            func.lower(col(ActorTable.current_handle)).like(pattern),
            func.lower(col(ActorTable.current_display_name)).like(pattern),
        )

    async def search_actors(
        self,
        q: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Actors whose handle/display name contain ``q`` (M9.F3).

        Returns ``ActorTable`` rows (type-erased), newest-activity first.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(ActorTable)
                .where(self._actor_search_clause(q))
                .order_by(col(ActorTable.last_seen_at_ingest).desc())
                .order_by(col(ActorTable.id))
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return list(result)

    async def count_search_actors(self, q: str) -> int:
        """Count actors matching the same substring search (M9.F3)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(func.count()).select_from(ActorTable).where(self._actor_search_clause(q))
            result = await session.exec(stmt)
            return int(result.one())

    async def list_actors(self, *, limit: int, offset: int = 0) -> list[object]:
        """All actors, newest-activity first (the unfiltered list surface).

        Same projection/ordering as :meth:`search_actors` without the substring
        clause; pairs with the existing :meth:`count_actors` for paging.
        Returns ``ActorTable`` rows (type-erased).
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(ActorTable)
                .order_by(col(ActorTable.last_seen_at_ingest).desc())
                .order_by(col(ActorTable.id))
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return list(result)

    async def upsert_source(
        self,
        *,
        kind: SourceKind,
        display_name: str,
        created_at: datetime,
    ) -> UUID:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(SourceTable).where(
                    SourceTable.kind == kind,
                    SourceTable.display_name == display_name,
                )
            )
            row = result.first()
            if row is None:
                row = SourceTable(
                    kind=kind,
                    display_name=display_name,
                    created_at=created_at,
                )
                session.add(row)
                await session.flush()
            row_id = row.id
            await session.commit()
            return row_id

    async def upsert_group(
        self,
        *,
        source_id: UUID,
        platform_groupid: str,
        kind: GroupKind,
        title: str | None,
        seen_at: datetime,
    ) -> UUID:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(GroupTable).where(
                    GroupTable.source_id == source_id,
                    GroupTable.platform_groupid == platform_groupid,
                )
            )
            row = result.first()
            if row is None:
                row = GroupTable(
                    source_id=source_id,
                    platform_groupid=platform_groupid,
                    kind=kind,
                    current_title=title,
                    first_seen_at_ingest=seen_at,
                    last_observed_at_ingest=seen_at,
                )
                session.add(row)
                await session.flush()
            else:
                row.current_title = title or row.current_title
                stored = row.last_observed_at_ingest
                if stored.tzinfo is None:
                    stored = stored.replace(tzinfo=UTC)
                row.last_observed_at_ingest = max(stored, seen_at)
                session.add(row)
                await session.flush()
            row_id = row.id
            await session.commit()
            return row_id

    async def upsert_actor(
        self,
        *,
        source_id: UUID,
        actor_key: str,
        platform_userid: str,
        handle: str | None,
        display_name: str | None,
        seen_at: datetime,
    ) -> UUID:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(ActorTable).where(ActorTable.actor_key == actor_key))
            row = result.first()
            if row is None:
                row = ActorTable(
                    actor_key=actor_key,
                    source_id=source_id,
                    platform_userid=platform_userid,
                    current_handle=handle,
                    current_display_name=display_name,
                    first_seen_at_ingest=seen_at,
                    last_seen_at_ingest=seen_at,
                    first_seen_at_source=seen_at,
                    last_seen_at_source=seen_at,
                )
                session.add(row)
                await session.flush()
            else:
                row.current_handle = handle or row.current_handle
                row.current_display_name = display_name or row.current_display_name
                li = row.last_seen_at_ingest
                stored_ingest = li if li.tzinfo is not None else li.replace(tzinfo=UTC)
                row.last_seen_at_ingest = max(stored_ingest, seen_at)
                if row.last_seen_at_source is None:
                    row.last_seen_at_source = seen_at
                else:
                    ls = row.last_seen_at_source
                    stored_src = ls if ls.tzinfo is not None else ls.replace(tzinfo=UTC)
                    if seen_at > stored_src:
                        row.last_seen_at_source = seen_at
                session.add(row)
                await session.flush()
            row_id = row.id
            await session.commit()
            return row_id


__all__ = ["ActorsMixin"]
