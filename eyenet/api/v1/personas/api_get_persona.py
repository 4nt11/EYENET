# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/personas/{persona_id} — persona detail (M9.F1)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.personas import PersonaDetail
from eyenet.contracts.attribution import PersonaRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["personas"])


@router.get(
    "/personas/{persona_id}",
    operation_id="personas_get",
    response_model=PersonaDetail,
    status_code=200,
)
async def personas_get(
    persona_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:personas"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> PersonaDetail:
    persona = cast("PersonaRow | None", await storage.get_persona(persona_id))
    if persona is None:
        raise ResourceNotFound("persona")
    # Mirror schemas.personas._label_or_synthesized: the wire contract is
    # non-null, so synthesize a stable placeholder when the label is unset.
    label = persona.label or f"persona-{persona.id.hex[:8]}"
    return PersonaDetail(
        persona_id=persona.id,
        label=label,
        member_count=len(persona.member_actor_ids),
        created_at=persona.created_at,
        updated_at=persona.updated_at,
    )
