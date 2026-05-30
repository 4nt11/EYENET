# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/auth/tokens — paginate the caller's own PATs (M9.A4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, get_current_user, get_storage
from eyenet.api.deps_paging import decode_cursor, encode_cursor
from eyenet.api.v1.schemas.auth import CursorPagePATSummary, PATSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["auth"])


@router.get(
    "/auth/tokens",
    operation_id="auth_list_tokens",
    response_model=CursorPagePATSummary,
    status_code=200,
)
async def auth_list_tokens(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = Query(default=False),
) -> CursorPagePATSummary:
    offset = decode_cursor(cursor)
    # Over-fetch by one to detect a further page without a second query.
    rows = await storage.list_personal_access_tokens(
        user_id=current_user.user_id,
        limit=limit + 1,
        offset=offset,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    estimated_total = (
        await storage.count_personal_access_tokens(user_id=current_user.user_id)
        if include_total
        else None
    )
    return CursorPagePATSummary(
        items=[
            PATSummary(
                token_id=r.token_id,
                name=r.name,
                prefix=r.prefix,
                scopes=list(r.scopes),
                created_at=r.created_at,
                last_used_at=r.last_used_at,
                expires_at=r.expires_at,
            )
            for r in page
        ],
        next_cursor=encode_cursor(offset + limit) if has_more else None,
        estimated_total=estimated_total,
    )
