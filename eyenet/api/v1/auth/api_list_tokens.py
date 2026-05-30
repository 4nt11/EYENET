# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/auth/tokens — paginate the caller's own PATs (M9.A4)."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import CurrentUser, get_current_user, get_storage
from eyenet.api.v1.schemas.auth import CursorPagePATSummary, PATSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["auth"])


def _encode_cursor(offset: int) -> str:
    """Opaque base64url cursor over an integer offset (newest-first page)."""
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _decode_cursor(cursor: str | None) -> int:
    """Decode the opaque cursor to a non-negative offset; 0 when absent.

    A malformed cursor is a client error → 422 (reuses the app's
    RequestValidationError → problem+json handler).
    """
    if cursor is None:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise RequestValidationError(
            [{"loc": ("query", "cursor"), "msg": "malformed cursor", "type": "value_error"}],
        ) from exc
    if offset < 0:
        raise RequestValidationError(
            [{"loc": ("query", "cursor"), "msg": "malformed cursor", "type": "value_error"}],
        )
    return offset


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
    offset = _decode_cursor(cursor)
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
        next_cursor=_encode_cursor(offset + limit) if has_more else None,
        estimated_total=estimated_total,
    )
