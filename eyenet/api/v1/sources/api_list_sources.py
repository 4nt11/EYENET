# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/sources — list configured Sources (M9.D1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.sources import CursorPageSourceSummary, SourceSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["sources"])


@router.get(
    "/sources",
    operation_id="sources_list",
    response_model=CursorPageSourceSummary,
    status_code=200,
)
async def sources_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPageSourceSummary:
    rows = await storage.list_sources(limit=page.fetch_limit, offset=page.offset)
    items: list[SourceSummary] = []
    for row in rows[: page.limit]:
        # active SourceDomain count per row (§3.8). N+1 over a small-operator
        # source list is acceptable; revisit if a deployment grows many Sources.
        active = await storage.list_source_domains(source_id=row.id)
        items.append(SourceSummary.from_domain(row, active_domain_count=len(active)))
    estimated_total = await storage.count_sources() if page.include_total else None
    return CursorPageSourceSummary(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
