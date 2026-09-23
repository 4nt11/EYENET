# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/clearance/grants — list clearance grants (§4.8). Requires admin:clearance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.clearance import (
    ClearanceGrantSummary,
    CursorPageClearanceGrantSummary,
)
from eyenet.api.v1.schemas.enums import ClearanceScope
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["clearance"])


@router.get(
    "/clearance/grants",
    operation_id="clearance_list_grants",
    response_model=CursorPageClearanceGrantSummary,
    status_code=200,
)
async def clearance_list_grants(
    _: Annotated[CurrentUser, Depends(RequireScope("admin:clearance"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    active_only: Annotated[int, Query(ge=0, le=1)] = 0,
    user_id: Annotated[UUID | None, Query()] = None,
    scope: Annotated[ClearanceScope | None, Query()] = None,
) -> CursorPageClearanceGrantSummary:
    now = datetime.now(tz=UTC)
    rows = await storage.list_clearance_grants(
        user_id=user_id,
        scope=scope,
        active_only=bool(active_only),
        now=now,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    estimated_total = (
        await storage.count_clearance_grants(
            user_id=user_id, scope=scope, active_only=bool(active_only), now=now
        )
        if page.include_total
        else None
    )
    return CursorPageClearanceGrantSummary(
        items=[ClearanceGrantSummary.from_domain(r, now=now) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
