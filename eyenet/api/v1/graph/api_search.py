# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/graph/search — actor lookup by handle/display name (M9.F3)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.actors import ActorSummary, CursorPageActorSummary
from eyenet.contracts.source import SourceRow
from eyenet.models.actor import ActorTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graph"])


@router.get(
    "/graph/search",
    operation_id="graph_search",
    response_model=CursorPageActorSummary,
    status_code=200,
)
async def graph_search(
    _: Annotated[CurrentUser, Depends(RequireScope("read:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    q: Annotated[str, Query(min_length=1, max_length=256)],
) -> CursorPageActorSummary:
    rows = cast(
        "list[ActorTable]",
        await storage.search_actors(q, limit=page.fetch_limit, offset=page.offset),
    )
    estimated_total = await storage.count_search_actors(q) if page.include_total else None
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
