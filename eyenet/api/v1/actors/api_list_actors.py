# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors — the unfiltered actor list (browse surface).

Mirrors ``graph_search`` (handle/display substring lookup) without the query
filter, so the operator can page the whole actor roster. Same ``ActorSummary``
projection and per-page source-kind resolution.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.actors import ActorSummary, CursorPageActorSummary, actor_primary_handle
from eyenet.contracts.source import SourceRow
from eyenet.models.actor import ActorTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["actors"])

ActorSort = Literal["recent", "messages", "observations", "handle"]


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
    is_bot: Annotated[bool | None, Query()] = None,
    group_id: Annotated[UUID | None, Query()] = None,
    min_messages: Annotated[int | None, Query(ge=0)] = None,
    min_observations: Annotated[int | None, Query(ge=0)] = None,
    max_messages: Annotated[int | None, Query(ge=0)] = None,
    max_observations: Annotated[int | None, Query(ge=0)] = None,
    sort: Annotated[ActorSort, Query()] = "recent",
) -> CursorPageActorSummary:
    rows = cast(
        "list[tuple[ActorTable, int, int]]",
        await storage.list_actors(
            limit=page.fetch_limit,
            offset=page.offset,
            sort=sort,
            is_bot=is_bot,
            group_id=group_id,
            min_messages=min_messages,
            min_observations=min_observations,
            max_messages=max_messages,
            max_observations=max_observations,
        ),
    )
    estimated_total = (
        await storage.count_actors(
            is_bot=is_bot,
            group_id=group_id,
            min_messages=min_messages,
            min_observations=min_observations,
            max_messages=max_messages,
            max_observations=max_observations,
        )
        if page.include_total
        else None
    )
    source_kinds: dict[UUID, str | None] = {}
    items: list[ActorSummary] = []
    for actor, msg_count, obs_count in rows[: page.limit]:
        if actor.source_id not in source_kinds:
            src = cast("SourceRow | None", await storage.get_source(actor.source_id))
            source_kinds[actor.source_id] = src.kind.value if src is not None else None
        kind = source_kinds[actor.source_id]
        items.append(
            ActorSummary(
                actor_id=actor.id,
                primary_handle=actor_primary_handle(actor),
                platforms=[kind] if kind is not None else [],
                score=None,
                is_bot=actor.is_bot_self_declared,
                message_count=msg_count,
                observation_count=obs_count,
            )
        )
    return CursorPageActorSummary(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
