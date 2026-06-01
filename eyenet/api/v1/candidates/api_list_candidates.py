# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/candidates — the triage queue (M9.D3).

Filter by ``state`` / ``source_id`` / ``min_score``; sorted score DESC,
last_observed_at_ingest DESC. The ``case_id`` filter (§3.9) is deferred — it
resolves through seed-roots (D4, not in this milestone).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.candidates import CandidateSummary, CursorPageCandidateSummary
from eyenet.contracts.enums import CandidateState
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["candidates"])


@router.get(
    "/candidates",
    operation_id="candidates_list",
    response_model=CursorPageCandidateSummary,
    status_code=200,
)
async def candidates_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:candidates"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    state: Annotated[CandidateState | None, Query()] = None,
    source_id: Annotated[UUID | None, Query()] = None,
    min_score: Annotated[float | None, Query(ge=0.0)] = None,
) -> CursorPageCandidateSummary:
    rows = await storage.list_candidates(
        state=state,
        source_id=source_id,
        min_score=min_score,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    estimated_total = (
        await storage.count_candidates(state=state, source_id=source_id, min_score=min_score)
        if page.include_total
        else None
    )
    return CursorPageCandidateSummary(
        items=[CandidateSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
