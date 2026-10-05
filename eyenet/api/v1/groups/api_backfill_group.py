# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/groups/{group_id}/backfill — queue a deep backfill.

THREAD backfill: sweeps stay shallow (page 1) for breadth; when a thread is
worth its deep pages, the operator queues it here and the collector fetches ALL
its pages. CATEGORY backfill: a one-shot override to re-sweep an explicit page
RANGE of a category (creation-sorted) when a fresh leak sank past the steady
window. Both read-only against the board. Requires `write:groups`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

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


class BackfillRequest(BaseModel):
    """Optional page range for a CATEGORY backfill (ignored for a thread)."""

    from_page: int | None = Field(default=None, ge=1)
    to_page: int | None = Field(default=None, ge=1)


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
    body: BackfillRequest | None = None,
) -> ForumReplyResult:
    group = await storage.get_group(group_id)
    if group is None:
        raise ResourceNotFound("group")
    if group.kind not in (GroupKind.FORUM_THREAD, GroupKind.FORUM_CATEGORY):
        raise ConflictError("backfill is only for forum threads or categories")

    req = body or BackfillRequest()
    from_page: int | None = None
    to_page: int | None = None
    if group.kind is GroupKind.FORUM_CATEGORY:
        # A category backfill needs an explicit range; page 1 alone is what the
        # steady sweep already does, so require from_page.
        if req.from_page is None:
            raise ConflictError("category backfill requires from_page")
        from_page = req.from_page
        to_page = req.to_page if req.to_page is not None else req.from_page
        if to_page < from_page:
            raise ConflictError("to_page must be >= from_page")

    request_id = await storage.create_forum_backfill_request(
        source_id=group.source_id,
        group_id=group_id,
        requested_by=str(current_user.user_id),
        requested_at=datetime.now(tz=UTC),
        from_page=from_page,
        to_page=to_page,
    )
    await audit.emit(
        event="eyenet.audit.forum.backfill_enqueued",
        subject_kind="group",
        subject_id=group_id,
        system_user_id=current_user.user_id,
        payload={"request_id": str(request_id)},
    )
    return ForumReplyResult(request_id=request_id, state="pending")
