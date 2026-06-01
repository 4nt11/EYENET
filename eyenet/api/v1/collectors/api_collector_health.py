# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/collectors/health — fleet health snapshot (M9.D2).

MUST mount before `/collectors/{collector_id}` (literal vs UUID path param).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.collectors import CollectorFleetHealthView
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["collectors"])


@router.get(
    "/collectors/health",
    operation_id="collectors_health",
    response_model=CollectorFleetHealthView,
    status_code=200,
)
async def collectors_health(
    _: Annotated[CurrentUser, Depends(RequireScope("read:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> CollectorFleetHealthView:
    health = await storage.collector_fleet_health()
    return CollectorFleetHealthView.from_domain(health)
