# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/actors/{actor_id}/relationships — actors related by mention/forward."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.actors import RelationNeighbor, RelationshipList
from eyenet.contracts.enums import RelationKind
from eyenet.storage.repository import BaseRepository

_RelRow = tuple[UUID, str | None, str | None, RelationKind, int, datetime]

router = APIRouter(tags=["actors"])


@router.get(
    "/actors/{actor_id}/relationships",
    operation_id="actors_relationships",
    response_model=RelationshipList,
    status_code=200,
)
async def actors_relationships(
    actor_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> RelationshipList:
    if await storage.get_actor(actor_id) is None:
        raise ResourceNotFound("actor")
    outbound, inbound = await storage.actor_relations_for(actor_id, limit=limit)

    def _row(r: _RelRow) -> RelationNeighbor:
        other_id, handle, display, kind, count, last_seen = r
        return RelationNeighbor(
            actor_id=other_id,
            handle=handle,
            display_name=display,
            kind=kind,
            count=count,
            last_seen=last_seen,
        )

    return RelationshipList(
        outbound=[_row(r) for r in outbound],
        inbound=[_row(r) for r in inbound],
    )
