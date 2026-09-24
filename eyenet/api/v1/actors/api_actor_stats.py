# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors/stats — roster-wide filter bounds (max message/observation counts)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.actors import ActorStats
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/stats", operation_id="actors_stats", response_model=ActorStats, status_code=200
)
async def actors_stats(
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ActorStats:
    max_messages, max_observations = await storage.actor_stat_bounds()
    return ActorStats(max_messages=max_messages, max_observations=max_observations)
