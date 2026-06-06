# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/cases/{case_id}/collaborators — list active case collaborators.

Storage returns only active (non-revoked) collaborators; surfacing revoked rows
is a follow-on, so there is no ``active_only`` knob in v1.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import decode_cursor, encode_cursor
from eyenet.api.v1.cases._detail import require_case_visible, to_collaborator_summary
from eyenet.api.v1.schemas.cases import CursorPageCaseCollaboratorSummary
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}/collaborators",
    operation_id="cases_list_collaborators",
    response_model=CursorPageCaseCollaboratorSummary,
    status_code=200,
)
async def cases_list_collaborators(
    case_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 50,
) -> CursorPageCaseCollaboratorSummary:
    await require_case_visible(storage, case_id, current_user)
    rows = await storage.list_case_collaborators(case_id)
    offset = decode_cursor(cursor)
    window = rows[offset : offset + limit]
    has_more = len(rows) > offset + limit
    return CursorPageCaseCollaboratorSummary(
        items=[to_collaborator_summary(r) for r in window],
        next_cursor=encode_cursor(offset + limit) if has_more else None,
        estimated_total=len(rows),
    )
