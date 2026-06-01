# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/sources/{source_id} — single Source with domains inlined (M9.D1)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.sources import SourceDetail
from eyenet.api.v1.sources._detail import build_source_detail
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["sources"])


@router.get(
    "/sources/{source_id}",
    operation_id="sources_get",
    response_model=SourceDetail,
    status_code=200,
)
async def sources_get(
    source_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:sources"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> SourceDetail:
    detail = await build_source_detail(storage, source_id)
    if detail is None:
        raise ResourceNotFound("source")
    return detail
