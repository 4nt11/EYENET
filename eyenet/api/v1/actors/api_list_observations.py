# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors/{actor_id}/observations — paginated observations (M9.F1)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.actors import CursorPageObservationSummary, ObservationSummary
from eyenet.models.observation import ObservationTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}/observations",
    operation_id="actors_observations",
    response_model=CursorPageObservationSummary,
    status_code=200,
)
async def actors_observations(
    actor_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:observations"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> CursorPageObservationSummary:
    if await storage.get_actor(actor_id) is None:
        raise ResourceNotFound("actor")
    rows = cast(
        "list[ObservationTable]",
        await storage.observations_for_actor(
            actor_id, since=since, until=until, limit=page.fetch_limit, offset=page.offset
        ),
    )
    estimated_total = (
        await storage.count_observations_for_actor(actor_id, since=since, until=until)
        if page.include_total
        else None
    )
    return CursorPageObservationSummary(
        items=[ObservationSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
