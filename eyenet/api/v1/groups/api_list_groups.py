# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/groups — every group the operator has vision over (all sources).

A unified, source-agnostic view over `GroupCandidate`: joined groups (JOINED),
discovered-via-descent candidates, and groups seen directly in an identity's
dialogs/rooms (member_dialog). Sorted score DESC, last_observed DESC.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.groups import CursorPageGroupSummary, GroupSummary
from eyenet.contracts.enums import CandidateState
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["groups"])


@router.get(
    "/groups",
    operation_id="groups_list",
    response_model=CursorPageGroupSummary,
    status_code=200,
)
async def groups_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:groups"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    source_id: Annotated[UUID | None, Query()] = None,
    state: Annotated[CandidateState | None, Query()] = None,
) -> CursorPageGroupSummary:
    rows = await storage.list_candidates(
        state=state,
        source_id=source_id,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    estimated_total = (
        await storage.count_candidates(state=state, source_id=source_id)
        if page.include_total
        else None
    )
    return CursorPageGroupSummary(
        items=[GroupSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
