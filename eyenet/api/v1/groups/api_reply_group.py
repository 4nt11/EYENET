# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/groups/{group_id}/reply — enqueue an operator reply to unlock a thread.

A MyBB [hide] gate only reveals its payload after you reply. Replying is a WRITE
against the forum, so this endpoint does NOT post anything: it records the
operator's typed message as a PENDING request. The running collector — the only
component holding the session — posts it under its own throttle, honors flood
control, then re-fetches the thread. Requires `write:groups`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.api.v1.schemas.groups import ForumReplyRequest, ForumReplyResult
from eyenet.contracts.enums import GroupKind
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["groups"])


@router.post(
    "/groups/{group_id}/reply",
    operation_id="groups_reply",
    response_model=ForumReplyResult,
    status_code=202,
)
async def groups_reply(
    group_id: UUID,
    body: ForumReplyRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:groups"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> ForumReplyResult:
    group = await storage.get_group(group_id)
    if group is None:
        raise ResourceNotFound("group")
    if group.kind is not GroupKind.FORUM_THREAD:
        raise ConflictError("reply-to-unlock is only for forum threads")

    request_id = await storage.create_forum_reply_request(
        source_id=group.source_id,
        group_id=group_id,
        message=body.message,
        requested_by=str(current_user.user_id),
        requested_at=datetime.now(tz=UTC),
    )
    await audit.emit(
        event="eyenet.audit.forum.reply_enqueued",
        subject_kind="group",
        subject_id=group_id,
        system_user_id=current_user.user_id,
        # A forum WRITE: audit the intent. Length only — the message is the
        # operator's own words, retained on the request row, not duplicated here.
        payload={"request_id": str(request_id), "message_chars": len(body.message)},
    )
    return ForumReplyResult(request_id=request_id, state="pending")
