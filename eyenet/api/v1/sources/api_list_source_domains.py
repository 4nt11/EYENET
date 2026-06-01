# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/sources/{source_id}/domains — list a Source's SourceDomains (M9.D1)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.sources import SourceDomainView
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["sources"])


@router.get(
    "/sources/{source_id}/domains",
    operation_id="sources_list_domains",
    response_model=list[SourceDomainView],
    status_code=200,
)
async def sources_list_domains(
    source_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    include_removed: Annotated[bool, Query()] = False,
) -> list[SourceDomainView]:
    if cast("SourceRow | None", await storage.get_source(source_id)) is None:
        raise ResourceNotFound("source")
    rows = await storage.list_source_domains(source_id=source_id, include_removed=include_removed)
    return [SourceDomainView.from_domain(r) for r in rows]
