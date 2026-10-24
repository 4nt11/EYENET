# SPDX-License-Identifier: AGPL-3.0-or-later
"""StealerMixin — ULP processing state: read/upsert + the replay work-list."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import col, select

from eyenet.contracts.message import AttachmentRow
from eyenet.contracts.stealer import StealerProcessingRow
from eyenet.models.message import AttachmentTable
from eyenet.models.stealer import STEALER_DONE, StealerProcessingTable

from ._helpers import safe_session


class StealerMixin:
    async def get_stealer_processing(
        self, attachment_id: UUID
    ) -> StealerProcessingRow | None:
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
        """Stealer-marked attachments WITH a blob that still need processing — the
        startup replay work-list. Excludes rows already ``done``; includes never-tried
        and previously-``failed``/``running`` (retry). Newest-first (id DESC = uuid7).
        Generic LEFT JOIN — no dialect leak."""
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


__all__ = ["StealerMixin"]
