# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/identities/{identity_id} — one pool identity (read:collectors)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.identities import IdentityDetail
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["identities"])


@router.get(
    "/identities/{identity_id}",
    operation_id="identities_get",
    response_model=IdentityDetail,
    status_code=200,
)
async def identities_get(
    identity_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> IdentityDetail:
    row = await storage.get_identity(identity_id)
    if row is None:
        raise ResourceNotFound("identity")
    return IdentityDetail.from_domain(row)
