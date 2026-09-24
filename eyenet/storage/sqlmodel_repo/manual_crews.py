# SPDX-License-Identifier: AGPL-3.0-or-later
"""ManualCrewsMixin — CRUD for operator-curated actor groups (manual crews).

Persistent, hand-built crews, distinct from the derived /actor-groups crews.
Generic ANSI SQL only.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func
from sqlmodel import col, select

from eyenet.models.actor import ActorTable
from eyenet.models.manual_crew import ManualCrewMemberTable, ManualCrewTable

from ._helpers import safe_session

# Row shapes returned to the API layer. A crew list row carries the crew id, name,
# notes, member count and last-updated time; a member row carries the actor id,
# handle, display name and added time; the detail bundles the crew fields with its
# member rows.
ManualCrewRow = tuple[UUID, str, str | None, int, datetime]
ManualCrewMemberRow = tuple[UUID, str | None, str | None, datetime]
ManualCrewDetail = tuple[str, str | None, datetime, datetime, list[ManualCrewMemberRow]]


class ManualCrewsMixin:
    async def create_manual_crew(
        self, *, name: str, notes: str | None, created_by: UUID, now: datetime
    ) -> UUID:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = ManualCrewTable(
                name=name, notes=notes, created_by=created_by, created_at=now, updated_at=now
            )
            session.add(row)
            await session.flush()
            crew_id = row.id
            await session.commit()
        return crew_id

    async def manual_crew_exists(self, crew_id: UUID) -> bool:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = (
                await session.exec(select(ManualCrewTable.id).where(ManualCrewTable.id == crew_id))
            ).first()
        return row is not None

    async def list_manual_crews(self) -> list[ManualCrewRow]:
        """All manual crews, newest-updated first, with member counts."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            counts = dict(
                (
                    await session.exec(
                        select(
                            ManualCrewMemberTable.crew_id,
                            func.count(col(ManualCrewMemberTable.id)),
                        ).group_by(col(ManualCrewMemberTable.crew_id))
                    )
                ).all()
            )
            crews = (
                await session.exec(
                    select(ManualCrewTable).order_by(col(ManualCrewTable.updated_at).desc())
                )
            ).all()
            return [
                (c.id, c.name, c.notes, int(counts.get(c.id, 0)), c.updated_at) for c in crews
            ]

    async def get_manual_crew(self, crew_id: UUID) -> ManualCrewDetail | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            crew = (
                await session.exec(select(ManualCrewTable).where(ManualCrewTable.id == crew_id))
            ).first()
            if crew is None:
                return None
            rows = (
                await session.exec(
                    select(ManualCrewMemberTable, ActorTable)
                    .join(ActorTable, col(ManualCrewMemberTable.actor_id) == col(ActorTable.id))
                    .where(ManualCrewMemberTable.crew_id == crew_id)
                    .order_by(col(ManualCrewMemberTable.added_at))
                )
            ).all()
            members: list[ManualCrewMemberRow] = [
                (a.id, a.current_handle, a.current_display_name, m.added_at) for m, a in rows
            ]
            return (crew.name, crew.notes, crew.created_at, crew.updated_at, members)

    async def add_manual_crew_member(
        self, *, crew_id: UUID, actor_id: UUID, now: datetime
    ) -> bool:
        """Add an actor to a crew (idempotent). Returns False if the crew is gone."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            crew = (
                await session.exec(select(ManualCrewTable).where(ManualCrewTable.id == crew_id))
            ).first()
            if crew is None:
                return False
            existing = (
                await session.exec(
                    select(ManualCrewMemberTable.id).where(
                        ManualCrewMemberTable.crew_id == crew_id,
                        ManualCrewMemberTable.actor_id == actor_id,
                    )
                )
            ).first()
            if existing is None:
                session.add(
                    ManualCrewMemberTable(crew_id=crew_id, actor_id=actor_id, added_at=now)
                )
                crew.updated_at = now
                session.add(crew)
            await session.commit()
        return True

    async def remove_manual_crew_member(
        self, *, crew_id: UUID, actor_id: UUID, now: datetime
    ) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            await session.exec(
                delete(ManualCrewMemberTable).where(
                    col(ManualCrewMemberTable.crew_id) == crew_id,
                    col(ManualCrewMemberTable.actor_id) == actor_id,
                )
            )
            crew = (
                await session.exec(select(ManualCrewTable).where(ManualCrewTable.id == crew_id))
            ).first()
            if crew is not None:
                crew.updated_at = now
                session.add(crew)
            await session.commit()

    async def delete_manual_crew(self, crew_id: UUID) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            await session.exec(
                delete(ManualCrewMemberTable).where(
                    col(ManualCrewMemberTable.crew_id) == crew_id
                )
            )
            await session.exec(delete(ManualCrewTable).where(col(ManualCrewTable.id) == crew_id))
            await session.commit()
