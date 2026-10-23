# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/channels — groups marked as stealer-log collection targets.

The stealer-subsystem view over GroupTable ``category == 'stealer_logs'``
(the tag set by ``POST /v1/groups/{id}/category``). Gated by ``read:stealer``
(an EXPIRING clearance scope, not a baseline role) because the list of which
channels we farm for credential dumps is itself sensitive tradecraft.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.groups import GroupDetail
from eyenet.contracts.group import STEALER_LOG_CATEGORY
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["groups"])


@router.get(
    "/stealer/channels",
    operation_id="stealer_channels_list",
    response_model=list[GroupDetail],
    status_code=200,
)
async def stealer_channels_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    source_id: Annotated[UUID | None, Query()] = None,
) -> list[GroupDetail]:
    rows = await storage.list_groups_by_category(STEALER_LOG_CATEGORY, source_id=source_id)
    return [GroupDetail.from_row(r) for r in rows]
