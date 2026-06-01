# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/collectors/{collector_id} — single collector (M9.D2).

Full ``config`` requires ``read:collectors_config``; otherwise redacted.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.collectors import CollectorDetail
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["collectors"])


@router.get(
    "/collectors/{collector_id}",
    operation_id="collectors_get",
    response_model=CollectorDetail,
    status_code=200,
)
async def collectors_get(
    collector_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> CollectorDetail:
    row = await storage.get_collector(collector_id)
    if row is None:
        raise ResourceNotFound("collector")
    has_config_grant = "read:collectors_config" in current_user.effective_scopes
    return CollectorDetail.from_domain_detail(row, has_config_grant=has_config_grant)
