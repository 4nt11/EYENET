# SPDX-License-Identifier: AGPL-3.0-or-later
"""DocumentsMixin — put / get rows on DocumentTable.

Generic SQLModel ORM only (SELECT-then-add / session.get) — no dialect-specific
SQL, so MySQL/Postgres backends inherit this unchanged ([[feedback_no_dialect_leak_in_mixins]]).
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from eyenet.contracts.document import DocumentRow
from eyenet.models.document import DocumentTable

from ._helpers import safe_session


class DocumentsMixin:
    async def put_document(self, document_row: object) -> UUID:
        row = cast("DocumentRow", document_row)
        table = DocumentTable(**row.model_dump())
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return table.id

    async def get_document(self, document_id: UUID) -> DocumentRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(DocumentTable, document_id)
            if table is None:
                return None
            return DocumentRow.model_validate(table.model_dump())


__all__ = ["DocumentsMixin"]
