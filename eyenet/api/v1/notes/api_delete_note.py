# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/notes/{entity_type}/{entity_id} - remove an entity's operator note."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1._clearance import enforce_entity_tier_clearance
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["notes"])


@router.delete(
    "/notes/{entity_type}/{entity_id}",
    operation_id="notes_delete",
    status_code=204,
)
async def notes_delete(
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    entity_type: Annotated[str, Path(min_length=1, max_length=32)],
    entity_id: Annotated[UUID, Path()],
) -> None:
    await enforce_entity_tier_clearance(storage, current_user, entity_type, entity_id)
    if not await storage.delete_entity_note(entity_type=entity_type, entity_id=entity_id):
        raise ResourceNotFound("note")
