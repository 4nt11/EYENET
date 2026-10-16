# SPDX-License-Identifier: AGPL-3.0-or-later
"""EntityNotesMixin — one operator note per graph entity (upsert / get / delete).

Generic SQLModel ORM only (SELECT-then-add/update — no dialect leak,
[[feedback_no_dialect_leak_in_mixins]]).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import select

from eyenet.contracts.entity_note import EntityNoteRow
from eyenet.models.entity_note import EntityNoteTable

from ._helpers import safe_session


class EntityNotesMixin:
    async def set_entity_note(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        body: str,
        created_by_user_id: UUID,
        now: datetime | None = None,
    ) -> UUID:
        """Upsert the note for ``(entity_type, entity_id)``. On update the body and
        ``updated_at`` change; ``created_at`` / ``created_by_user_id`` are preserved.
        Returns the note id."""
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = (
                await session.exec(
                    select(EntityNoteTable).where(
                        EntityNoteTable.entity_type == entity_type,
                        EntityNoteTable.entity_id == entity_id,
                    )
                )
            ).first()
            if existing is not None:
                existing.body = body
                existing.updated_at = at
                session.add(existing)
                await session.commit()
                return existing.id
            row = EntityNoteTable(
                entity_type=entity_type,
                entity_id=entity_id,
                body=body,
                created_by_user_id=created_by_user_id,
                created_at=at,
                updated_at=at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    async def get_entity_note(self, *, entity_type: str, entity_id: UUID) -> EntityNoteRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = (
                await session.exec(
                    select(EntityNoteTable).where(
                        EntityNoteTable.entity_type == entity_type,
                        EntityNoteTable.entity_id == entity_id,
                    )
                )
            ).first()
            if row is None:
                return None
            return EntityNoteRow.model_validate(row.model_dump())

    async def delete_entity_note(self, *, entity_type: str, entity_id: UUID) -> bool:
        """Delete the note for an entity. Returns False if there was none."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = (
                await session.exec(
                    select(EntityNoteTable).where(
                        EntityNoteTable.entity_type == entity_type,
                        EntityNoteTable.entity_id == entity_id,
                    )
                )
            ).first()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


__all__ = ["EntityNotesMixin"]
