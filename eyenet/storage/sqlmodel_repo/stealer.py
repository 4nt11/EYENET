# SPDX-License-Identifier: AGPL-3.0-or-later
"""StealerMixin — ULP processing state: read/upsert + the replay work-list."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import col, select

from eyenet.contracts.message import AttachmentRow
from eyenet.contracts.stealer import StealerFamilyOverrideRow, StealerProcessingRow
from eyenet.models.message import AttachmentTable
from eyenet.models.stealer import (
    STEALER_DONE,
    StealerFamilyOverrideTable,
    StealerProcessingTable,
)

from ._helpers import safe_session


class StealerMixin:
    async def get_stealer_processing(self, attachment_id: UUID) -> StealerProcessingRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(StealerProcessingTable, attachment_id)
            if row is None:
                return None
            return StealerProcessingRow.model_validate(row.model_dump())

    async def set_stealer_processing(
        self,
        attachment_id: UUID,
        *,
        state: str,
        creds_extracted: int = 0,
        error: str | None = None,
    ) -> None:
        """Upsert the processing state for an attachment, bumping ``attempts`` each call.

        SELECT-then-add/update (generic ORM, no dialect leak)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(StealerProcessingTable, attachment_id)
            if row is None:
                row = StealerProcessingTable(attachment_id=attachment_id, attempts=1)
            else:
                row.attempts += 1
            row.state = state
            row.creds_extracted = creds_extracted
            row.error = error
            row.updated_at = datetime.now(tz=UTC)
            session.add(row)
            await session.commit()

    async def list_unprocessed_stealer_attachments(
        self, category: str, *, limit: int
    ) -> list[AttachmentRow]:
        """Stealer-marked attachments WITH a blob that still need processing: the
        startup replay work-list. Excludes rows already ``done``; includes never-tried
        and previously-``failed``/``running`` (retry). Newest-first (id DESC = uuid7).
        Generic LEFT JOIN, no dialect leak."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(AttachmentTable)
                .join(
                    StealerProcessingTable,
                    col(StealerProcessingTable.attachment_id) == col(AttachmentTable.id),
                    isouter=True,
                )
                .where(col(AttachmentTable.category) == category)
                .where(col(AttachmentTable.storage_uri).is_not(None))
                .where(
                    col(StealerProcessingTable.state).is_(None)
                    | (col(StealerProcessingTable.state) != STEALER_DONE)
                )
                .order_by(col(AttachmentTable.id).desc())
                .limit(limit)
            )
            result = await session.exec(stmt)
            return [AttachmentRow.model_validate(r.model_dump()) for r in list(result)]

    async def list_stealer_attachments_for_reindex(
        self, category: str, *, limit: int, after_id: UUID | None = None
    ) -> list[AttachmentRow]:
        """Reindex work-list: ALL stealer-marked attachments with a blob,
        regardless of processing state. Keyset-paged by id DESC so repeated
        calls with the last-seen ``after_id`` sweep the whole corpus without a
        growing OFFSET. Generic, no dialect leak."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(AttachmentTable)
                .where(col(AttachmentTable.category) == category)
                .where(col(AttachmentTable.storage_uri).is_not(None))
            )
            if after_id is not None:
                stmt = stmt.where(col(AttachmentTable.id) < after_id)
            stmt = stmt.order_by(col(AttachmentTable.id).desc()).limit(limit)
            result = await session.exec(stmt)
            return [AttachmentRow.model_validate(r.model_dump()) for r in list(result)]

    async def get_stealer_family_override(
        self, archive_sha256: str, victim_folder: str
    ) -> StealerFamilyOverrideRow | None:
        """Read one operator override by (archive, victim). Returns None
        when no override exists; the drawer falls back to the classifier
        verdict in that case."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(StealerFamilyOverrideTable, (archive_sha256, victim_folder))
            if row is None:
                return None
            return StealerFamilyOverrideRow.model_validate(row.model_dump())

    async def upsert_stealer_family_override(
        self,
        *,
        archive_sha256: str,
        victim_folder: str,
        slug: str,
        reason: str | None,
        author_user_id: UUID,
    ) -> StealerFamilyOverrideRow:
        """Create or replace the override for (archive, victim). Generic
        SELECT-then-add/update; dialect-neutral so a future MySQL backend
        does not need its own path."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(StealerFamilyOverrideTable, (archive_sha256, victim_folder))
            now = datetime.now(tz=UTC)
            if row is None:
                row = StealerFamilyOverrideTable(
                    archive_sha256=archive_sha256,
                    victim_folder=victim_folder,
                    slug=slug,
                    reason=reason,
                    author_user_id=author_user_id,
                    created_at=now,
                    updated_at=now,
                )
            else:
                row.slug = slug
                row.reason = reason
                row.author_user_id = author_user_id
                row.updated_at = now
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return StealerFamilyOverrideRow.model_validate(row.model_dump())

    async def list_stealer_family_overrides(self) -> list[StealerFamilyOverrideRow]:
        """Every override row. Used to drive the per-family P/R
        dashboard; the override set is intentionally small (hundreds,
        not millions) so a full sweep is cheap."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(StealerFamilyOverrideTable)
            result = await session.exec(stmt)
            return [StealerFamilyOverrideRow.model_validate(r.model_dump()) for r in list(result)]

    async def delete_stealer_family_override(self, archive_sha256: str, victim_folder: str) -> bool:
        """Remove the override. Returns True when a row was deleted,
        False when there was nothing to delete."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(StealerFamilyOverrideTable, (archive_sha256, victim_folder))
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


__all__ = ["StealerMixin"]
