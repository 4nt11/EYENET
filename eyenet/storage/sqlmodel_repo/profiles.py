# SPDX-License-Identifier: AGPL-3.0-or-later
"""ProfilesMixin — atomic flip of `is_current` inside a transaction."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from opentelemetry import trace
from sqlmodel import col, select

from eyenet.contracts.attribution import ProfileRow
from eyenet.models import ProfileTable

from ._helpers import safe_session

_tracer = trace.get_tracer("eyenet.storage.sqlmodel_repo.profiles")


class ProfilesMixin:
    async def get_current_profile(self, actor_id: UUID) -> object | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(ProfileTable)
                .where(ProfileTable.actor_id == actor_id)
                .where(col(ProfileTable.is_current).is_(True))
            )
            return result.first()

    async def upsert_current_profile(self, profile_row: object) -> None:
        row = cast("ProfileRow", profile_row)
        with _tracer.start_as_current_span(
            "storage.profiles.upsert_current",
            attributes={
                "actor.id": str(row.actor_id),
                "profile.version": row.version,
            },
        ):
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                existing_result = await session.exec(
                    select(ProfileTable)
                    .where(ProfileTable.actor_id == row.actor_id)
                    .where(col(ProfileTable.is_current).is_(True))
                )
                existing = existing_result.first()
                if existing is not None:
                    existing.is_current = False
                    session.add(existing)
                data = row.model_dump()
                data["is_current"] = True
                session.add(ProfileTable(**data))
                await session.commit()

    async def profile_history(self, actor_id: UUID) -> list[object]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(ProfileTable)
                .where(ProfileTable.actor_id == actor_id)
                .order_by(col(ProfileTable.version).asc())
            )
            result = await session.exec(stmt)
            return list(result)


__all__ = ["ProfilesMixin"]
