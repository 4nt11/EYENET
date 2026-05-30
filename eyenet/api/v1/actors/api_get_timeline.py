# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors/{actor_id}/timeline — merged messages + observations (M9.F1)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params, encode_cursor
from eyenet.api.v1.schemas.actors import CursorPageTimelineEntry, TimelineEntry
from eyenet.models.message import MessageTable
from eyenet.models.observation import ObservationTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}/timeline",
    operation_id="actors_timeline",
    response_model=CursorPageTimelineEntry,
    status_code=200,
)
async def actors_timeline(
    actor_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:observations"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> CursorPageTimelineEntry:
    if await storage.get_actor(actor_id) is None:
        raise ResourceNotFound("actor")
    # The timeline is the time-merge of two independently-ordered streams.
    # Over-fetch the leading `offset + limit + 1` of each, merge-sort newest-
    # first, then slice the requested window — correct for offset cursors at
    # small-operator scale (both streams are per-actor bounded).
    need = page.offset + page.limit + 1
    msgs = cast(
        "list[MessageTable]",
        await storage.messages_for_actor(actor_id, since=since, until=until, limit=need, offset=0),
    )
    obs = cast(
        "list[ObservationTable]",
        await storage.observations_for_actor(
            actor_id, since=since, until=until, limit=need, offset=0
        ),
    )
    entries = [TimelineEntry.from_message(m) for m in msgs]
    entries += [TimelineEntry.from_observation(o) for o in obs]
    entries.sort(key=lambda e: (e.ts, e.id), reverse=True)
    end = page.offset + page.limit
    window = entries[page.offset : end]
    has_more = len(entries) > end
    estimated_total = None
    if page.include_total:
        estimated_total = await storage.count_messages_for_actor(
            actor_id, since=since, until=until
        ) + await storage.count_observations_for_actor(actor_id, since=since, until=until)
    return CursorPageTimelineEntry(
        items=window,
        next_cursor=encode_cursor(end) if has_more else None,
        estimated_total=estimated_total,
    )
