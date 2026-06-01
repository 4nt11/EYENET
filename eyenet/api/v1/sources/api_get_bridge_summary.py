# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/sources/{source_id}/bridge-summary — resolution counts (M9.D1)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.sources import BridgeSummary
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["sources"])


@router.get(
    "/sources/{source_id}/bridge-summary",
    operation_id="sources_bridge_summary",
    response_model=BridgeSummary,
    status_code=200,
)
async def sources_bridge_summary(
    source_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> BridgeSummary:
    if cast("SourceRow | None", await storage.get_source(source_id)) is None:
        raise ResourceNotFound("source")
    summary = await storage.source_bridge_summary(source_id=source_id)
    return BridgeSummary.from_domain(summary)
