# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/groups/{group_id}/category — mark a group's collection class.

Sets (or clears, with ``category: null``) the GroupTable ``category`` tag that
routes a channel into a collection subsystem. The stealer-log collection class
is the first consumer: marking a channel ``stealer_logs`` lifts it past the
collector's attachment size gate so the multi-GB archive drops are captured.

Gated by ``admin:stealer`` (a permanent grant-only capability, not a baseline
role), because mislabelling a channel silently re-routes what the collector
pulls down.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_bus, get_storage
from eyenet.api.v1.schemas.groups import GroupDetail, SetGroupCategoryRequest
from eyenet.contracts.bus import Bus
from eyenet.contracts.group import GROUP_CATEGORY_CHANGED_SUBJECT
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["groups"])


@router.post(
    "/groups/{group_id}/category",
    operation_id="groups_mark_category",
    response_model=GroupDetail,
    status_code=200,
)
async def groups_mark_category(
    group_id: UUID,
    body: SetGroupCategoryRequest,
    _: Annotated[CurrentUser, Depends(RequireScope("admin:stealer"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    bus: Annotated[Bus, Depends(get_bus)],
) -> GroupDetail:
    if not await storage.set_group_category(group_id, body.category):
        raise ResourceNotFound("group")
    row = await storage.get_group(group_id)
    if row is None:  # vanished between set and read — treat as not found
        raise ResourceNotFound("group")
    # Broadcast so every collector re-reads its source's marked set at once (the
    # mark only ever happens post-join, so this is the sole path by which a mark
    # takes effect on live traffic). Empty payload; each collector re-reads itself.
    await bus.publish(GROUP_CATEGORY_CHANGED_SUBJECT, b"")
    return GroupDetail.from_row(row)
