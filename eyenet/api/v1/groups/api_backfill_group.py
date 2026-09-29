# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/groups/{group_id}/backfill — queue a deep backfill of one thread.

Sweeps stay shallow (page 1) for breadth; when a specific thread is worth its
deep pages, the operator queues a backfill here. The running collector fetches
ALL pages of that thread under its throttle. Read-only against the board.
Requires `write:groups`.
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
from eyenet.api.v1.schemas.groups import ForumReplyResult
from eyenet.contracts.enums import GroupKind
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["groups"])


@router.post(
    "/groups/{group_id}/backfill",
    operation_id="groups_backfill",
    response_model=ForumReplyResult,
    status_code=202,
)
async def groups_backfill(
    group_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:groups"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> ForumReplyResult:
    group = await storage.get_group(group_id)
    if group is None:
        raise ResourceNotFound("group")
    if group.kind is not GroupKind.FORUM_THREAD:
        raise ConflictError("backfill is only for forum threads")

    request_id = await storage.create_forum_backfill_request(
        source_id=group.source_id,
        group_id=group_id,
        requested_by=str(current_user.user_id),
        requested_at=datetime.now(tz=UTC),
    )
    await audit.emit(
        event="eyenet.audit.forum.backfill_enqueued",
        subject_kind="group",
        subject_id=group_id,
        system_user_id=current_user.user_id,
        payload={"request_id": str(request_id)},
    )
    return ForumReplyResult(request_id=request_id, state="pending")
