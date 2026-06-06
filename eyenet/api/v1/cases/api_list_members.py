# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/cases/{case_id}/members — list active members of a case.

The storage layer returns only active (non-removed) members; surfacing
soft-removed rows is a follow-on (it needs a storage flag), so there is no
``active_only`` knob in v1.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import decode_cursor, encode_cursor
from eyenet.api.v1.cases._detail import require_case_visible, to_member_summary
from eyenet.api.v1.schemas.cases import CursorPageCaseMemberSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}/members",
    operation_id="cases_list_members",
    response_model=CursorPageCaseMemberSummary,
    status_code=200,
)
async def cases_list_members(
    case_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 50,
) -> CursorPageCaseMemberSummary:
    await require_case_visible(storage, case_id, current_user)
    rows = await storage.list_case_members(case_id)
    offset = decode_cursor(cursor)
    window = rows[offset : offset + limit]
    has_more = len(rows) > offset + limit
    return CursorPageCaseMemberSummary(
        items=[to_member_summary(r) for r in window],
        next_cursor=encode_cursor(offset + limit) if has_more else None,
        estimated_total=len(rows),
    )
