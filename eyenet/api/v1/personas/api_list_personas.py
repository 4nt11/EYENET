# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/personas — the persona browse surface (M9.F3-style list).

Newest-first page of persona summaries. `member_count` is `len(member_actor_ids)`
off the persona row (the cheap forward view), so no per-row membership query.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.personas import CursorPagePersonaSummary, PersonaSummary
from eyenet.models.persona import PersonaTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["personas"])


@router.get(
    "/personas",
    operation_id="personas_list",
    response_model=CursorPagePersonaSummary,
    status_code=200,
)
async def personas_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:personas"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPagePersonaSummary:
    rows = cast(
        "list[PersonaTable]",
        await storage.list_personas(limit=page.fetch_limit, offset=page.offset),
    )
    estimated_total = await storage.count_personas() if page.include_total else None
    items = [
        PersonaSummary.from_domain(p, member_count=len(p.member_actor_ids))
        for p in rows[: page.limit]
    ]
    return CursorPagePersonaSummary(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
