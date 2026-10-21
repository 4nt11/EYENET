# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/messages/{message_id} — one post in full.

Author, source, timestamp, body, the artifacts found in it, and any incident
labels. The focused by-id read a message lacked (it lived only inside a group's
message list / an actor's timeline before)."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.messages._build import build_message_detail
from eyenet.api.v1.schemas.messages import MessageDetail
from eyenet.models.message import MessageTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["messages"])


@router.get(
    "/messages/{message_id}",
    operation_id="messages_get",
    response_model=MessageDetail,
    status_code=200,
)
async def messages_get(
    message_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:observations"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> MessageDetail:
    msg = await storage.get_message(message_id)
    if msg is None:
        raise ResourceNotFound("message")
    return await build_message_detail(storage, cast("MessageTable", msg))
