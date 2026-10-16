# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/notes/{entity_type}/{entity_id} - upsert the operator note for an entity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1._clearance import enforce_entity_tier_clearance
from eyenet.api.v1.schemas.entity_notes import NoteResponse, SetNoteRequest
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["notes"])


@router.put(
    "/notes/{entity_type}/{entity_id}",
    operation_id="notes_set",
    response_model=NoteResponse,
    status_code=200,
)
async def notes_set(
    body: SetNoteRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    entity_type: Annotated[str, Path(min_length=1, max_length=32)],
    entity_id: Annotated[UUID, Path()],
) -> NoteResponse:
    await enforce_entity_tier_clearance(storage, current_user, entity_type, entity_id)
    await storage.set_entity_note(
        entity_type=entity_type,
        entity_id=entity_id,
        body=body.body,
        created_by_user_id=current_user.user_id,
        now=datetime.now(tz=UTC),
    )
    row = await storage.get_entity_note(entity_type=entity_type, entity_id=entity_id)
    if row is None:  # pragma: no cover - just upserted
        raise ResourceNotFound("note")
    return NoteResponse.from_domain(row)
