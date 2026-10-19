# SPDX-License-Identifier: AGPL-3.0-or-later
"""ActorsMixin — source / group / actor upsert + actor_key resolve."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, or_
from sqlmodel import col, select

from eyenet.contracts.actor import ActorRow
from eyenet.contracts.enums import GroupKind, MembershipRole, SourceKind
from eyenet.contracts.group import GroupRow
from eyenet.contracts.source import SourceRow
from eyenet.models import ActorTable, GroupTable, MembershipTable, SourceTable
from eyenet.models.actor import ActorAliasHistoryTable
from eyenet.models.message import MessageTable
from eyenet.models.observation import ObservationTable

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
        operator_assessment=row.operator_assessment,
        provenance=row.provenance,
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

    async def actors_by_ids(self, ids: Sequence[UUID]) -> dict[UUID, object]:
        """Batch actor fetch by primary-key id -> ``{id: ActorRow}`` in ONE query.

        Replaces a per-id ``get_actor`` N+1 (the actor-groups label resolver fired
        one round-trip per crew member; hundreds of members = seconds of pooled
        round-trips). Missing ids are simply absent from the map."""
        if not ids:
            return {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            rows = (
                await session.exec(select(ActorTable).where(col(ActorTable.id).in_(list(ids))))
            ).all()
            return {row.id: _row_to_actor(row) for row in rows}

    async def get_source(self, source_id: UUID) -> object | None:
        """Return the :class:`SourceRow` for a primary-key id, or None (M9.F1).

        Used by the actor-detail handler to project an actor's single platform.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(SourceTable, source_id)
            return _row_to_source(row) if row is not None else None

    def _individuals_only(self) -> ColumnElement[bool]:
        """Exclude channel/group senders from the individual-actor roster: their
        ``platform_userid`` is a negative -100 marked peer id (e.g.
        ``-1003573398394``). They are entities, not people, and were surfacing as
        bogus actors. Forward origins that are people keep positive ids and stay."""
        return col(ActorTable.platform_userid).not_like("-%")

    # Per-actor message / observation counts as correlated scalar subqueries. At
    # small-operator scale a correlated count per row is cheap and keeps the query
    # generic (no join fan-out to de-duplicate). ponytail: a materialized
    # actor_stats table is the upgrade if the roster outgrows this.
    def _msg_count(self) -> Any:
        return (
            select(func.count())
            .select_from(MessageTable)
            .where(col(MessageTable.actor_id) == col(ActorTable.id))
            .scalar_subquery()
        )

    def _obs_count(self) -> Any:
        return (
            select(func.count())
            .select_from(ObservationTable)
            .where(col(ObservationTable.actor_id) == col(ActorTable.id))
            .scalar_subquery()
        )

    def _apply_actor_filters(
        self,
        stmt: Any,
        mc: Any,
        oc: Any,
        *,
        is_bot: bool | None,
        group_id: UUID | None,
        min_messages: int | None,
        min_observations: int | None,
        max_messages: int | None,
        max_observations: int | None,
    ) -> Any:
        stmt = stmt.where(self._individuals_only())
        if is_bot is not None:
            stmt = stmt.where(col(ActorTable.is_bot_self_declared) == is_bot)
        if group_id is not None:
            stmt = stmt.where(
                exists().where(
                    col(MessageTable.actor_id) == col(ActorTable.id),
                    col(MessageTable.group_id) == group_id,
                )
            )
        if min_messages is not None:
            stmt = stmt.where(mc >= min_messages)
        if max_messages is not None:
            stmt = stmt.where(mc <= max_messages)
        if min_observations is not None:
            stmt = stmt.where(oc >= min_observations)
        if max_observations is not None:
            stmt = stmt.where(oc <= max_observations)
        return stmt

    async def actor_stat_bounds(self) -> tuple[int, int]:
        """(max messages, max observations) held by any individual actor — the
        domain ceilings for the filter sliders."""
        mc, oc = self._msg_count(), self._obs_count()
        stmt = (
            select(func.coalesce(func.max(mc), 0), func.coalesce(func.max(oc), 0))
            .select_from(ActorTable)
            .where(self._individuals_only())
        )
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = (await session.exec(stmt)).one()
            return int(row[0]), int(row[1])

    def _order_actors(self, stmt: Any, mc: Any, oc: Any, sort: str) -> Any:
        if sort == "messages":
            return stmt.order_by(mc.desc())
        if sort == "observations":
            return stmt.order_by(oc.desc())
        if sort == "handle":
            return stmt.order_by(col(ActorTable.current_handle).asc())
        return stmt.order_by(col(ActorTable.last_seen_at_ingest).desc())

    async def count_actors(
        self,
        *,
        is_bot: bool | None = None,
        group_id: UUID | None = None,
        min_messages: int | None = None,
        min_observations: int | None = None,
        max_messages: int | None = None,
        max_observations: int | None = None,
    ) -> int:
        """Number of INDIVIDUAL actors matching the filters (channels excluded)."""
        mc, oc = self._msg_count(), self._obs_count()
        inner = self._apply_actor_filters(
            select(ActorTable.id),
            mc,
            oc,
            is_bot=is_bot,
            group_id=group_id,
            min_messages=min_messages,
            min_observations=min_observations,
            max_messages=max_messages,
            max_observations=max_observations,
        ).subquery()
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(func.count()).select_from(inner))
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

    async def list_actors(
        self,
        *,
        limit: int,
        offset: int = 0,
        is_bot: bool | None = None,
        group_id: UUID | None = None,
        min_messages: int | None = None,
        min_observations: int | None = None,
        max_messages: int | None = None,
        max_observations: int | None = None,
        sort: str = "recent",
    ) -> list[object]:
        """Individual actors matching the filters, with per-actor message +
        observation counts. Returns ``(ActorTable, message_count, observation_count)``
        tuples (type-erased). ``sort``: recent | messages | observations | handle.
        """
        mc, oc = self._msg_count(), self._obs_count()
        stmt = self._apply_actor_filters(
            select(ActorTable, mc.label("mc"), oc.label("oc")),
            mc,
            oc,
            is_bot=is_bot,
            group_id=group_id,
            min_messages=min_messages,
            min_observations=min_observations,
            max_messages=max_messages,
            max_observations=max_observations,
        )
        stmt = (
            self._order_actors(stmt, mc, oc, sort)
            .order_by(col(ActorTable.id))
            .limit(limit)
            .offset(offset)
        )
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(stmt)
            return [(row[0], int(row[1]), int(row[2])) for row in result.all()]

    async def set_actor_assessment(self, actor_id: UUID, assessment: str | None) -> bool:
        """Set the operator free-text assessment. Returns False if no such actor.

        SELECT-then-update (generic ORM, no dialect leak)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(ActorTable, actor_id)
            if row is None:
                return False
            row.operator_assessment = assessment
            session.add(row)
            await session.commit()
            return True

    async def actor_aliases(self, actor_id: UUID) -> list[object]:
        """Alias history for an actor, newest-first; ActorAliasHistoryTable
        rows type-erased. Backs ActorDetail.aliases + the real alias_count."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(ActorAliasHistoryTable)
                .where(col(ActorAliasHistoryTable.actor_id) == actor_id)
                .order_by(col(ActorAliasHistoryTable.observed_from).desc())
                .order_by(col(ActorAliasHistoryTable.id))
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
    ) -> tuple[UUID, bool]:
        """Returns ``(group_id, search_changed)``. ``search_changed`` is True when
        the group is newly created or its searchable field (title) actually
        changed — the gate for emitting ``entity.group.changed`` (GLOBAL_SEARCH.md).
        """
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
                search_changed = True
            else:
                new_title = title or row.current_title
                search_changed = new_title != row.current_title
                row.current_title = new_title
                stored = row.last_observed_at_ingest
                if stored.tzinfo is None:
                    stored = stored.replace(tzinfo=UTC)
                row.last_observed_at_ingest = max(stored, seen_at)
                session.add(row)
                await session.flush()
            row_id = row.id
            await session.commit()
            return row_id, search_changed

    async def get_group(self, group_id: UUID) -> GroupRow | None:
        """Return one GroupRow by id, or ``None`` (used by the leave path)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(GroupTable, group_id)
            if table is None:
                return None
            data = table.model_dump()
            for k in ("first_seen_at_ingest", "last_observed_at_ingest"):
                v = data.get(k)
                if v is not None and v.tzinfo is None:
                    data[k] = v.replace(tzinfo=UTC)
            return GroupRow.model_validate(data)

    async def upsert_actor(
        self,
        *,
        source_id: UUID,
        actor_key: str,
        platform_userid: str,
        handle: str | None,
        display_name: str | None,
        seen_at: datetime,
        is_bot: bool = False,
    ) -> tuple[UUID, bool]:
        """Returns ``(actor_id, search_changed)``. ``search_changed`` is True when
        the actor is newly created or a searchable field (handle / display name)
        actually changed — the gate for emitting ``entity.actor.changed``
        (GLOBAL_SEARCH.md). Note: ``notes``/``operator_assessment``/aliases are
        set on other paths, which emit their own event.
        """
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
                    is_bot_self_declared=is_bot,
                )
                session.add(row)
                await session.flush()
                search_changed = True
            else:
                new_handle = handle or row.current_handle
                new_display = display_name or row.current_display_name
                search_changed = (
                    new_handle != row.current_handle or new_display != row.current_display_name
                )
                row.current_handle = new_handle
                row.current_display_name = new_display
                # Sticky: once Telegram tells us it's a bot, keep it flagged.
                row.is_bot_self_declared = is_bot or row.is_bot_self_declared
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
            return row_id, search_changed

    async def upsert_membership(
        self,
        *,
        actor_id: UUID,
        group_id: UUID,
        role: MembershipRole,
        seen_at: datetime,
        joined_at_source: datetime | None = None,
    ) -> tuple[UUID, bool]:
        """Upsert an actor<->group membership with its platform role. The role is the
        cross-platform primitive: Discord rank, IRC user mode, Matrix power level all
        land here (MODELS §2.2). Unique on (actor_id, group_id). Returns
        ``(membership_id, role_changed)`` — ``role_changed`` is True on create or when
        the role actually changed, and a seen membership is un-left (``left_at`` cleared).
        Generic ORM only (no dialect SQL): safe in the shared mixin layer."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(MembershipTable).where(
                    MembershipTable.actor_id == actor_id,
                    MembershipTable.group_id == group_id,
                )
            )
            row = result.first()
            if row is None:
                row = MembershipTable(
                    actor_id=actor_id,
                    group_id=group_id,
                    role=role,
                    joined_at_source=joined_at_source,
                    joined_at_ingest=seen_at,
                )
                session.add(row)
                await session.flush()
                changed = True
            else:
                changed = row.role != role
                row.role = role
                if joined_at_source is not None and row.joined_at_source is None:
                    row.joined_at_source = joined_at_source
                row.left_at_ingest = None  # we just saw them, so they are present
                session.add(row)
                await session.flush()
            row_id = row.id
            await session.commit()
            return row_id, changed


__all__ = ["ActorsMixin"]
