# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/personas/{persona_id}/members — paginated members (M9.F1)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.personas import CursorPagePersonaMember, PersonaMember
from eyenet.models.persona import PersonaMembershipTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["personas"])


@router.get(
    "/personas/{persona_id}/members",
    operation_id="personas_members",
    response_model=CursorPagePersonaMember,
    status_code=200,
)
async def personas_members(
    persona_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:personas"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPagePersonaMember:
    if await storage.get_persona(persona_id) is None:
        raise ResourceNotFound("persona")
    rows = cast(
        "list[PersonaMembershipTable]",
        await storage.list_persona_memberships(
            persona_id, limit=page.fetch_limit, offset=page.offset
        ),
    )
    estimated_total = (
        await storage.count_persona_memberships(persona_id) if page.include_total else None
    )
    return CursorPagePersonaMember(
        items=[PersonaMember.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
