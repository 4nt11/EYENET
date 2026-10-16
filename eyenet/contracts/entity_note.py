# SPDX-License-Identifier: AGPL-3.0-or-later
"""`EntityNote` contract — one operator note per graph entity. Surface: db."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ._base import DbRowBase


class EntityNoteRow(DbRowBase):
    """Persisted per-entity note (upsert by (entity_type, entity_id))."""

    entity_type: str
    entity_id: UUID
    body: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
