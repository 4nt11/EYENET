# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/search — unified cross-entity search (GLOBAL_SEARCH.md §4)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, UnprocessableError, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.search import CursorPageSearchHit, SearchHit
from eyenet.models.search import SearchDocumentTable
from eyenet.storage.query import UnknownFieldError
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["search"])


def _csv(value: str | None) -> list[str] | None:
    """Split a CSV query facet into a clean list, or None when absent/empty."""
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return parts or None


@router.get(
    "/search",
    operation_id="search_global",
    response_model=CursorPageSearchHit,
    status_code=200,
)
async def search_global(
    _: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    q: Annotated[str, Query(min_length=1, max_length=256)],
    types: Annotated[str | None, Query(description="CSV of entity types to include")] = None,
    status: Annotated[str | None, Query(description="CSV of status facets to include")] = None,
    source: Annotated[UUID | None, Query(description="Restrict to one source_id")] = None,
) -> CursorPageSearchHit:
    types_list = _csv(types)
    status_list = _csv(status)
    try:
        rows = cast(
            "list[SearchDocumentTable]",
            await storage.search_global(
                q,
                types=types_list,
                status=status_list,
                source_id=source,
                limit=page.fetch_limit,
                offset=page.offset,
            ),
        )
        estimated_total = (
            await storage.count_search_global(
                q, types=types_list, status=status_list, source_id=source
            )
            if page.include_total
            else None
        )
        facets = await storage.search_global_facets(
            q, types=types_list, status=status_list, source_id=source
        )
    except UnknownFieldError as exc:
        raise UnprocessableError(str(exc)) from exc
    items = [SearchHit.from_domain(row) for row in rows[: page.limit]]
    # Resolve source UUIDs -> human display names for row + facet rendering.
    source_ids = {sid for sid in facets["by_source"] if sid}
    source_ids.update(str(h.source_id) for h in items if h.source_id is not None)
    source_labels: dict[str, str] = {}
    for sid in source_ids:
        row = await storage.get_source(UUID(sid))
        if row is not None:
            source_labels[sid] = getattr(row, "display_name", sid)
    return CursorPageSearchHit(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
        by_type=facets["by_type"],
        by_source=facets["by_source"],
        source_labels=source_labels,
    )
