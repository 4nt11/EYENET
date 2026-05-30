# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/graph/stats — global graph counters (M9.F3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.enums import LinkageState
from eyenet.api.v1.schemas.graph import GraphStats, LinkageStateCounts
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graph"])


@router.get(
    "/graph/stats",
    operation_id="graph_stats",
    response_model=GraphStats,
    status_code=200,
)
async def graph_stats(
    _: Annotated[CurrentUser, Depends(RequireScope("read:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> GraphStats:
    return GraphStats(
        actors=await storage.count_actors(),
        personas=await storage.count_personas(),
        linkages=LinkageStateCounts(
            proposed=await storage.count_linkages(state=LinkageState.PROPOSED),
            suspected=await storage.count_linkages(state=LinkageState.SUSPECTED),
            confirmed=await storage.count_linkages(state=LinkageState.CONFIRMED),
            rejected=await storage.count_linkages(state=LinkageState.REJECTED),
        ),
        observations=await storage.count_observations(),
        computed_at=datetime.now(tz=UTC),
    )
