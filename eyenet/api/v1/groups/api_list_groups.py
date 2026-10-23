# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/groups — every group the operator has vision over (all sources).

A unified, source-agnostic view over `GroupCandidate`: joined groups (JOINED),
discovered-via-descent candidates, and groups seen directly in an identity's
dialogs/rooms (member_dialog). Sorted score DESC, last_observed DESC.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.groups import (
    CursorPageGroupSummary,
    GroupSummary,
    status_filter,
)
from eyenet.api.v1.sources._detail import resolve_forum_base_url
from eyenet.contracts.enums import CandidateState
from eyenet.contracts.source import SourceRow
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
    member_dialog: Annotated[
        bool | None,
        Query(description="Filter by dialog membership (true=member, false=discovered-only)."),
    ] = None,
    q: Annotated[
        str | None,
        Query(description="Case-insensitive substring over the group name + platform id."),
    ] = None,
) -> CursorPageGroupSummary:
    # `status` (if given) is the bundled operator facet and wins; otherwise the
    # direct member_dialog + state params flow through independently (the FE drives
    # its membership and monitored axes separately for coherent pagination).
    states: list[CandidateState] | None = None
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
        q=q,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    estimated_total = (
        await storage.count_candidates(
            state=state, source_id=source_id, states=states, member_dialog=member_dialog, q=q
        )
        if page.include_total
        else None
    )
    items = [GroupSummary.from_domain(r) for r in rows[: page.limit]]
    # Tag each item with its forum (label + base URL) so the reader can tell apart
    # categories whose slugs collide across forums. Resolve ONCE per distinct
    # source on the page (a handful), not per row.
    # ponytail: linear per-distinct-source resolve; fine for monitored reads.
    for sid in {it.source_id for it in items}:
        src = cast("SourceRow | None", await storage.get_source(sid))
        if src is None:
            continue
        url = await resolve_forum_base_url(storage, src)
        for it in items:
            if it.source_id == sid:
                it.source_label = src.display_name
                it.source_url = url
    return CursorPageGroupSummary(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
