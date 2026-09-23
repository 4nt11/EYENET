# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/clearance/grants/{grant_id} — full grant detail (§4.8). Requires admin:clearance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.clearance import ClearanceGrantDetail
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["clearance"])


@router.get(
    "/clearance/grants/{grant_id}",
    operation_id="clearance_get_grant",
    response_model=ClearanceGrantDetail,
    status_code=200,
)
async def clearance_get_grant(
    grant_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("admin:clearance"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ClearanceGrantDetail:
    row = await storage.get_clearance_grant(grant_id)
    if row is None:
        raise ResourceNotFound("clearance grant")
    return ClearanceGrantDetail.from_domain(row, now=datetime.now(tz=UTC))
