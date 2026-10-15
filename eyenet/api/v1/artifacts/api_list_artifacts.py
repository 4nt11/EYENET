# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/artifacts — browse deduped infrastructure artifacts.

Each row is one distinct value with read-time aggregates off the mention edge:
how many messages it appeared in, how many distinct actors and groups, and the
first/last time it was seen. Filter by ``kind``, substring ``q`` on the value,
and ``resolution_state``; sort by recency, mention count, value, or first seen.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.artifacts import ArtifactSummary, CursorPageArtifactSummary
from eyenet.contracts.enums import ResolutionState
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["artifacts"])

ArtifactSort = Literal["recent", "mentions", "value", "first_seen"]


@router.get(
    "/artifacts",
    operation_id="artifacts_list",
    response_model=CursorPageArtifactSummary,
    status_code=200,
)
async def artifacts_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    kind: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=256)] = None,
    resolution_state: Annotated[ResolutionState | None, Query()] = None,
    sort: Annotated[ArtifactSort, Query()] = "recent",
) -> CursorPageArtifactSummary:
    rows = await storage.list_infrastructure_artifacts(
        kind=kind,
        q=q,
        resolution_state=resolution_state,
        sort=sort,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    estimated_total = (
        await storage.count_infrastructure_artifacts(
            kind=kind, q=q, resolution_state=resolution_state
        )
        if page.include_total
        else None
    )
    items = [
        ArtifactSummary(
            id=art.id,
            kind=art.kind,
            value=art.value,
            resolution_state=art.resolution_state,
            resolved_to_source_id=art.resolved_to_source_id,
            first_seen_at_ingest=art.first_seen_at_ingest,
            last_seen_at_ingest=art.last_seen_at_ingest,
            mention_count=mentions,
            distinct_actors=actors,
            distinct_groups=groups,
            first_mention_at=first_ts,
            last_mention_at=last_ts,
        )
        for art, mentions, actors, groups, first_ts, last_ts in rows[: page.limit]
    ]
    return CursorPageArtifactSummary(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
