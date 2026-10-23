# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/groups/{group_id} - one group's core record (graph-inspector dossier)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.groups import GroupDetail
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["groups"])


@router.get(
    "/groups/{group_id}",
    operation_id="groups_get",
    response_model=GroupDetail,
    status_code=200,
)
async def groups_get(
    group_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> GroupDetail:
    row = await storage.get_group(group_id)
    if row is None:
        raise ResourceNotFound("group")
    return GroupDetail.from_row(row)
