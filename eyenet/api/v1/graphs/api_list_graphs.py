# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/graphs - the current operator's saved graphs, newest-updated first."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.saved_graphs import CursorPageGraphSummary, GraphSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["graphs"])


@router.get(
    "/graphs",
    operation_id="graphs_list",
    response_model=CursorPageGraphSummary,
    status_code=200,
)
async def graphs_list(
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:graph"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPageGraphSummary:
    rows = await storage.list_investigation_graphs(
        created_by_user_id=current_user.user_id,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    # No count method for saved graphs, so estimated_total is never populated.
    return CursorPageGraphSummary(
        items=[GraphSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=None,
    )
