# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/groups — every group the operator has vision over (all sources).

A unified, source-agnostic view over `GroupCandidate`: joined groups (JOINED),
discovered-via-descent candidates, and groups seen directly in an identity's
dialogs/rooms (member_dialog). Sorted score DESC, last_observed DESC.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.groups import (
    CursorPageGroupSummary,
    GroupSummary,
    status_filter,
)
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
    status: Annotated[
        str | None,
        Query(
            description="Operator-facing status filter: monitored|joining|requested|approving"
            "|member_unmonitored|discovered|rejected|failed|parked"
        ),
    ] = None,
) -> CursorPageGroupSummary:
    states: list[CandidateState] | None = None
    member_dialog: bool | None = None
    if status is not None:
        try:
            states, member_dialog = status_filter(status)
        except KeyError:
            raise HTTPException(status_code=400, detail=f"unknown status: {status}") from None
    rows = await storage.list_candidates(
        state=state,
        source_id=source_id,
        states=states,
        member_dialog=member_dialog,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    estimated_total = (
        await storage.count_candidates(
            state=state, source_id=source_id, states=states, member_dialog=member_dialog
        )
        if page.include_total
        else None
    )
    return CursorPageGroupSummary(
        items=[GroupSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
