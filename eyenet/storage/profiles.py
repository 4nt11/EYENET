"""SQLiteProfileStore — atomic flip of `is_current` inside a transaction."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from opentelemetry import trace
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from eyenet.contracts.attribution import ProfileRow
from eyenet.contracts.storage import ProfileStore
from eyenet.models import ProfileTable

_tracer = trace.get_tracer("eyenet.storage.profiles")


class SQLiteProfileStore(ProfileStore):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def get_current(self, actor_id: UUID) -> object | None:
        with Session(self._engine) as session:
            return session.exec(
                select(ProfileTable)
                .where(ProfileTable.actor_id == actor_id)
                .where(col(ProfileTable.is_current).is_(True))
            ).first()

    async def upsert_current(self, profile_row: object) -> None:
        row = cast("ProfileRow", profile_row)
        with (
            _tracer.start_as_current_span(
                "storage.profiles.upsert_current",
                attributes={
                    "actor.id": str(row.actor_id),
                    "profile.version": row.version,
                },
            ),
            Session(self._engine) as session,
        ):
            # Demote the existing current row, if any.
            existing = session.exec(
                select(ProfileTable)
                .where(ProfileTable.actor_id == row.actor_id)
                .where(col(ProfileTable.is_current).is_(True))
            ).first()
            if existing is not None:
                existing.is_current = False
                session.add(existing)
            data = row.model_dump()
            data["is_current"] = True
            session.add(ProfileTable(**data))
            session.commit()

    async def history(self, actor_id: UUID) -> list[object]:
        with Session(self._engine) as session:
            stmt = (
                select(ProfileTable)
                .where(ProfileTable.actor_id == actor_id)
                .order_by(col(ProfileTable.version).asc())
            )
            return list(session.exec(stmt))  # type: ignore[arg-type]


__all__ = ["SQLiteProfileStore"]
