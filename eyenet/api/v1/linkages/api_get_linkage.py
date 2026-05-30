# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/linkages/{linkage_id} — linkage detail incl. evidence (M9.F2)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.linkages._shared import resolve_decider
from eyenet.api.v1.schemas.linkages import LinkageDetail
from eyenet.models.linkage import LinkageTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["linkages"])


@router.get(
    "/linkages/{linkage_id}",
    operation_id="linkages_get",
    response_model=LinkageDetail,
    status_code=200,
)
async def linkages_get(
    linkage_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:linkages"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> LinkageDetail:
    row = await storage.get_linkage(linkage_id)
    if row is None:
        raise ResourceNotFound("linkage")
    decided_by = await resolve_decider(storage, row.decided_by, {})
    return LinkageDetail.from_domain(cast("LinkageTable", row), decided_by)
