# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/threads/{thread_id} — one thread: its OP post in full + thread meta.

A thread is identified by its ``group_id`` today (threads ride on the group
model), so ``thread_id`` is that id and the OP is the group's earliest post."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.messages._build import build_message_detail
from eyenet.api.v1.schemas.messages import ThreadDetail
from eyenet.models.message import MessageTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["threads"])


@router.get(
    "/threads/{thread_id}",
    operation_id="threads_get",
    response_model=ThreadDetail,
    status_code=200,
)
async def threads_get(
    thread_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:observations"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ThreadDetail:
    group = await storage.get_group(thread_id)
    if group is None:
        raise ResourceNotFound("thread")
    op = await storage.op_message_for_group(thread_id)
    if op is None:
        raise ResourceNotFound("thread")  # a group with no posts has no OP to show
    source = await storage.get_source(group.source_id)
    return ThreadDetail(
        thread_id=thread_id,
        source_id=group.source_id,
        source_display=getattr(source, "display_name", None),
        title=group.current_title,
        post_count=await storage.count_messages_for_group(thread_id),
        op=await build_message_detail(storage, cast("MessageTable", op)),
    )
