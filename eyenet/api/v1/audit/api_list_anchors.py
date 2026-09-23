# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/audit/anchors — external-witness anchor records (§5.9). Requires read:audit."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import decode_cursor, encode_cursor
from eyenet.api.v1.schemas.anchors import Anchor, CursorPageAnchor
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/anchors",
    operation_id="audit_list_anchors",
    response_model=CursorPageAnchor,
    status_code=200,
)
async def audit_list_anchors(
    _: Annotated[CurrentUser, Depends(RequireScope("read:audit"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> CursorPageAnchor:
    offset = decode_cursor(cursor)
    rows = await storage.list_anchors(since=since, until=until, limit=limit + 1, offset=offset)
    has_more = len(rows) > limit
    next_cursor = encode_cursor(offset + limit) if has_more else None
    return CursorPageAnchor(
        items=[Anchor.from_domain(r) for r in rows[:limit]],
        next_cursor=next_cursor,
        estimated_total=None,
    )
