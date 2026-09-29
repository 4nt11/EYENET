# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/groups/{group_id}/messages — raw posts in a group (forum thread / chat).

The read surface for a forum/channel reader: the full retained posts of a thread,
oldest-first, with the evidence-faithful `body_html` and the `reply_gated` flag.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params, encode_cursor
from eyenet.api.v1.schemas.groups import CursorPageGroupMessage, GroupMessage
from eyenet.models.message import MessageTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["groups"])


@router.get(
    "/groups/{group_id}/messages",
    operation_id="groups_messages",
    response_model=CursorPageGroupMessage,
    status_code=200,
)
async def groups_messages(
    group_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:observations"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPageGroupMessage:
    if await storage.get_group(group_id) is None:
        raise ResourceNotFound("group")
    rows = cast(
        "list[MessageTable]",
        await storage.messages_for_group(group_id, limit=page.limit + 1, offset=page.offset),
    )
    has_more = len(rows) > page.limit
    page_rows = rows[: page.limit]
    # Attach the classifier's verdict per post so the reader shows what each was tagged.
    labels = await storage.incident_labels_for_messages([m.id for m in page_rows])
    items = [GroupMessage.from_message(m, labels.get(m.id)) for m in page_rows]
    estimated_total = (
        await storage.count_messages_for_group(group_id) if page.include_total else None
    )
    return CursorPageGroupMessage(
        items=items,
        next_cursor=encode_cursor(page.offset + page.limit) if has_more else None,
        estimated_total=estimated_total,
    )
