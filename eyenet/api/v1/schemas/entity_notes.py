# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request/response schemas for per-entity notes (the canvas Notes tab)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema

if TYPE_CHECKING:
    from eyenet.contracts.entity_note import EntityNoteRow


class NoteResponse(ApiSchema):
    """The note for one entity."""

    id: UUID
    entity_type: str
    entity_id: UUID
    body: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, row: EntityNoteRow) -> NoteResponse:
        return cls(
            id=row.id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            body=row.body,
            created_by_user_id=row.created_by_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class SetNoteRequest(ApiSchema):
    """Body of ``PUT /v1/notes/{entity_type}/{entity_id}``."""

    body: str = Field(min_length=1, max_length=16384)


__all__ = ["NoteResponse", "SetNoteRequest"]
