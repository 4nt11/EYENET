# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/collectors — list the collector fleet (M9.D2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.collectors import CollectorSummary, CursorPageCollectorSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["collectors"])


@router.get(
    "/collectors",
    operation_id="collectors_list",
    response_model=CursorPageCollectorSummary,
    status_code=200,
)
async def collectors_list(
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPageCollectorSummary:
    has_config_grant = "read:collectors_config" in current_user.effective_scopes
    rows = await storage.list_collectors(limit=page.fetch_limit, offset=page.offset)
    estimated_total = await storage.count_collectors() if page.include_total else None
    return CursorPageCollectorSummary(
        items=[
            CollectorSummary.from_domain(r, has_config_grant=has_config_grant)
            for r in rows[: page.limit]
        ],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
