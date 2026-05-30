# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/linkages — paginated list, filterable by state/method/time (M9.F2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.linkages._shared import resolve_decider
from eyenet.api.v1.schemas.enums import LinkageState
from eyenet.api.v1.schemas.linkages import CursorPageLinkageSummary, LinkageSummary
from eyenet.contracts.attribution import LinkageRow
from eyenet.models.linkage import LinkageTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["linkages"])


@router.get(
    "/linkages",
    operation_id="linkages_list",
    response_model=CursorPageLinkageSummary,
    status_code=200,
)
async def linkages_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:linkages"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    state: Annotated[LinkageState | None, Query()] = None,
    method: Annotated[str | None, Query(max_length=64)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> CursorPageLinkageSummary:
    rows = cast(
        "list[LinkageRow]",
        await storage.list_linkages(
            state=state,
            limit=page.fetch_limit,
            offset=page.offset,
            method=method,
            since=since,
            until=until,
        ),
    )
    estimated_total = (
        await storage.count_linkages(state=state, method=method, since=since, until=until)
        if page.include_total
        else None
    )
    cache: dict[str, UUID | None] = {}
    items: list[LinkageSummary] = []
    for row in rows[: page.limit]:
        decided_by = await resolve_decider(storage, row.decided_by, cache)
        items.append(LinkageSummary.from_domain(cast("LinkageTable", row), decided_by))
    return CursorPageLinkageSummary(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
