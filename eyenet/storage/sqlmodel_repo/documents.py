# SPDX-License-Identifier: AGPL-3.0-or-later
"""DocumentsMixin — put / get rows on DocumentTable.

Generic SQLModel ORM only (SELECT-then-add / session.get) — no dialect-specific
SQL, so MySQL/Postgres backends inherit this unchanged ([[feedback_no_dialect_leak_in_mixins]]).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from eyenet.contracts.document import DocumentRow
from eyenet.models.document import DocumentTable

from ._helpers import safe_session

if TYPE_CHECKING:
    from datetime import datetime

    from eyenet.contracts.enums import SensitivityTier


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

    async def settle_document_classification(
        self,
        document_id: UUID,
        *,
        tier: SensitivityTier,
        extracted_text: str | None,
        embedded_meta: dict[str, Any],
        classification: dict[str, Any],
        review_required: bool,
        ingested_at: datetime,
    ) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(DocumentTable, document_id)
            if row is None:
                raise ValueError(f"document {document_id} not found")
            row.classifier_tier = tier
            row.extracted_text = extracted_text
            row.embedded_meta = embedded_meta
            row.classification = classification
            row.review_required = review_required
            row.ingested_at = ingested_at
            session.add(row)
            await session.commit()


__all__ = ["DocumentsMixin"]
