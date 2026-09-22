# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors — the unfiltered actor list (browse surface).

Mirrors ``graph_search`` (handle/display substring lookup) without the query
filter, so the operator can page the whole actor roster. Same ``ActorSummary``
projection and per-page source-kind resolution.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.actors import ActorSummary, CursorPageActorSummary
from eyenet.contracts.source import SourceRow
from eyenet.models.actor import ActorTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["actors"])


@router.get(
    "/actors",
    operation_id="actors_list",
    response_model=CursorPageActorSummary,
    status_code=200,
)
async def actors_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPageActorSummary:
    rows = cast(
        "list[ActorTable]",
        await storage.list_actors(limit=page.fetch_limit, offset=page.offset),
    )
    estimated_total = await storage.count_actors() if page.include_total else None
    # Resolve each actor's single platform, caching by source id (a page
    # typically spans only a handful of distinct sources).
    source_kinds: dict[UUID, str | None] = {}
    items: list[ActorSummary] = []
    for actor in rows[: page.limit]:
        if actor.source_id not in source_kinds:
            src = cast("SourceRow | None", await storage.get_source(actor.source_id))
            source_kinds[actor.source_id] = src.kind.value if src is not None else None
        kind = source_kinds[actor.source_id]
        items.append(
            ActorSummary(
                actor_id=actor.id,
                primary_handle=actor.current_handle or actor.platform_userid,
                platforms=[kind] if kind is not None else [],
                score=None,
            )
        )
    return CursorPageActorSummary(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
