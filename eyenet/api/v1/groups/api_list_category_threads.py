# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/groups/{category_id}/threads — threads discovered under a forum category.

The reader's navigation layer: a FORUM_CATEGORY group -> the FORUM_THREAD groups
found inside it (via the category->thread link the collector records at crawl
time), most-recent-first. Open a thread's posts with GET .../messages.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_storage,
)
from eyenet.api.deps_paging import CursorParams, cursor_params, encode_cursor
from eyenet.api.v1.schemas.groups import CursorPageGroupThread, GroupThread
from eyenet.contracts.enums import GroupKind
from eyenet.models.group import GroupTable
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
) -> CursorPageGroupThread:
    category = await storage.get_group(category_id)
    if category is None:
        raise ResourceNotFound("group")
    if category.kind is not GroupKind.FORUM_CATEGORY:
        raise ConflictError("threads are listed under a forum category")
    rows = cast(
        "list[GroupTable]",
        await storage.list_threads_for_category(
            source_id=category.source_id,
            category_platform_groupid=category.platform_groupid,
            limit=page.limit + 1,
            offset=page.offset,
        ),
    )
    has_more = len(rows) > page.limit
    items = [GroupThread.from_group(g) for g in rows[: page.limit]]
    return CursorPageGroupThread(
        items=items,
        next_cursor=encode_cursor(page.offset + page.limit) if has_more else None,
        estimated_total=None,
    )
