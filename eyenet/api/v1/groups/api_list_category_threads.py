# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/groups/{category_id}/threads — threads discovered under a forum category.

The reader's navigation layer: a FORUM_CATEGORY group -> the FORUM_THREAD groups
found inside it (via the category->thread link the collector records at crawl
time), most-recent-first. Open a thread's posts with GET .../messages.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_storage,
)
from eyenet.api.deps_paging import CursorParams, cursor_params, encode_cursor
from eyenet.api.v1.schemas.groups import (
    CategorySearchHit,
    CursorPageCategorySearchHit,
    CursorPageGroupThread,
    GroupThread,
)
from eyenet.contracts.enums import GroupKind
from eyenet.contracts.incident import ThreadSummaryRow
from eyenet.models.group import GroupTable
from eyenet.models.message import MessageTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["groups"])


@router.get(
    "/groups/{category_id}/threads",
    operation_id="groups_category_threads",
    response_model=CursorPageGroupThread,
    status_code=200,
)
async def groups_category_threads(
    category_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:observations"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    sort: Annotated[str, Query(pattern="^(recent|date)$")] = "recent",
    country: Annotated[list[str] | None, Query()] = None,
    label: Annotated[list[str] | None, Query()] = None,
) -> CursorPageGroupThread:
    # ?sort=date orders by the OP post time; ?country= / ?label= repeat (OR within each)
    # to filter to threads whose OP resolved to a country / carries an incident label.
    category = await storage.get_group(category_id)
    if category is None:
        raise ResourceNotFound("group")
    if category.kind is not GroupKind.FORUM_CATEGORY:
        raise ConflictError("threads are listed under a forum category")
    rows = cast(
        "list[tuple[GroupTable, ThreadSummaryRow | None]]",
        await storage.list_threads_for_category(
            source_id=category.source_id,
            category_platform_groupid=category.platform_groupid,
            limit=page.limit + 1,
            offset=page.offset,
            countries=country,
            labels=label,
            sort=sort,
        ),
    )
    has_more = len(rows) > page.limit
    page_rows = rows[: page.limit]
    # The OP's classifier labels, fresh (joined off op_message_id, not cached in the summary).
    op_ids = [s.op_message_id for _g, s in page_rows if s is not None]
    op_labels = await storage.incident_labels_for_messages(op_ids)
    items = [
        GroupThread.from_group(g, s, op_labels.get(s.op_message_id) if s is not None else None)
        for g, s in page_rows
    ]
    estimated_total = (
        await storage.count_threads_for_category(
            source_id=category.source_id,
            category_platform_groupid=category.platform_groupid,
            countries=country,
            labels=label,
        )
        if page.include_total
        else None
    )
    return CursorPageGroupThread(
        items=items,
        next_cursor=encode_cursor(page.offset + page.limit) if has_more else None,
        estimated_total=estimated_total,
    )


@router.get(
    "/groups/{category_id}/search",
    operation_id="groups_category_search",
    response_model=CursorPageCategorySearchHit,
    status_code=200,
)
async def groups_category_search(
    category_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:observations"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    q: Annotated[str, Query(min_length=1, max_length=256)],
) -> CursorPageCategorySearchHit:
    """Body-search across every thread under a forum category (the reader's category-level
    search) — find a post without opening each thread. Each hit carries the thread it came
    from so the UI can link to it. Newest match first."""
    category = await storage.get_group(category_id)
    if category is None:
        raise ResourceNotFound("group")
    if category.kind is not GroupKind.FORUM_CATEGORY:
        raise ConflictError("search across threads is a forum-category operation")
    rows = cast(
        "list[tuple[MessageTable, UUID, str | None]]",
        await storage.search_messages_in_category(
            source_id=category.source_id,
            category_platform_groupid=category.platform_groupid,
            q=q,
            limit=page.limit + 1,
            offset=page.offset,
        ),
    )
    has_more = len(rows) > page.limit
    items = [CategorySearchHit.from_row(m, tgid, title) for m, tgid, title in rows[: page.limit]]
    estimated_total = (
        await storage.count_messages_in_category(
            source_id=category.source_id,
            category_platform_groupid=category.platform_groupid,
            q=q,
        )
        if page.include_total
        else None
    )
    return CursorPageCategorySearchHit(
        items=items,
        next_cursor=encode_cursor(page.offset + page.limit) if has_more else None,
        estimated_total=estimated_total,
    )
