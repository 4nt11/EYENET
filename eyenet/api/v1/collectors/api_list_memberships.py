# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/collectors/{collector_id}/memberships — active group memberships (M9.D2).

Active memberships only (``left_at IS NULL``). The ``?include_left=true``
historical view needs a storage method that returns closed memberships, which
Group C didn't ship — deferred.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.collectors import CollectorMembershipView
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["collectors"])


@router.get(
    "/collectors/{collector_id}/memberships",
    operation_id="collectors_list_memberships",
    response_model=list[CollectorMembershipView],
    status_code=200,
)
async def collectors_list_memberships(
    collector_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> list[CollectorMembershipView]:
    if await storage.get_collector(collector_id) is None:
        raise ResourceNotFound("collector")
    rows = await storage.list_active_memberships(collector_id=collector_id)
    return [CollectorMembershipView.from_domain(r) for r in rows]
