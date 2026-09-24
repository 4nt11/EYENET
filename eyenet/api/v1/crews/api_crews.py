# SPDX-License-Identifier: AGPL-3.0-or-later
"""CRUD for manual (operator-curated) crews: /v1/crews.

Persistent, hand-built actor groups, distinct from the derived /actor-groups
crews. Reads need read:actors, writes need write:actors (operator curation of
actors). Handle resolution reuses the relation builder's handle index.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.manual_crews import (
    AddCrewMemberRequest,
    CreateManualCrewRequest,
    CreateManualCrewResult,
    ManualCrewDetail,
    ManualCrewList,
    ManualCrewMemberEntry,
    ManualCrewSummary,
)
from eyenet.relations.mentions import normalize_handle
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["crews"])


async def _detail(storage: BaseRepository, crew_id: UUID) -> ManualCrewDetail:
    row = await storage.get_manual_crew(crew_id)
    if row is None:
        raise ResourceNotFound("crew")
    name, notes, created_at, updated_at, members = row
    return ManualCrewDetail(
        crew_id=crew_id,
        name=name,
        notes=notes,
        created_at=created_at,
        updated_at=updated_at,
        members=[
            ManualCrewMemberEntry(actor_id=a, handle=h, display_name=d, added_at=t)
            for a, h, d, t in members
        ],
    )


@router.post(
    "/crews", operation_id="crews_create", response_model=CreateManualCrewResult, status_code=201
)
async def crews_create(
    body: CreateManualCrewRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> CreateManualCrewResult:
    now = datetime.now(tz=UTC)
    crew_id = await storage.create_manual_crew(
        name=body.name, notes=body.notes, created_by=current_user.user_id, now=now
    )
    for actor_id in body.members:
        await storage.add_manual_crew_member(crew_id=crew_id, actor_id=actor_id, now=now)
    return CreateManualCrewResult(crew_id=crew_id)


@router.get("/crews", operation_id="crews_list", response_model=ManualCrewList, status_code=200)
async def crews_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ManualCrewList:
    rows = await storage.list_manual_crews()
    items = [
        ManualCrewSummary(
            crew_id=cid, name=name, notes=notes, member_count=count, updated_at=updated_at
        )
        for cid, name, notes, count, updated_at in rows
    ]
    return ManualCrewList(items=items, count=len(items))


@router.get(
    "/crews/{crew_id}", operation_id="crews_get", response_model=ManualCrewDetail, status_code=200
)
async def crews_get(
    crew_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ManualCrewDetail:
    return await _detail(storage, crew_id)


@router.post(
    "/crews/{crew_id}/members",
    operation_id="crews_add_member",
    response_model=ManualCrewDetail,
    status_code=200,
)
async def crews_add_member(
    crew_id: UUID,
    body: AddCrewMemberRequest,
    _: Annotated[CurrentUser, Depends(RequireScope("write:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ManualCrewDetail:
    actor_id = body.actor_id
    if actor_id is None:
        key = normalize_handle(body.handle)
        index = await storage.handle_to_actor_index()
        actor_id = index.get(key) if key else None
        if actor_id is None:
            raise ResourceNotFound("actor")
    ok = await storage.add_manual_crew_member(
        crew_id=crew_id, actor_id=actor_id, now=datetime.now(tz=UTC)
    )
    if not ok:
        raise ResourceNotFound("crew")
    return await _detail(storage, crew_id)


@router.delete(
    "/crews/{crew_id}/members/{actor_id}",
    operation_id="crews_remove_member",
    response_model=ManualCrewDetail,
    status_code=200,
)
async def crews_remove_member(
    crew_id: UUID,
    actor_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("write:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ManualCrewDetail:
    if not await storage.manual_crew_exists(crew_id):
        raise ResourceNotFound("crew")
    await storage.remove_manual_crew_member(
        crew_id=crew_id, actor_id=actor_id, now=datetime.now(tz=UTC)
    )
    return await _detail(storage, crew_id)


@router.delete("/crews/{crew_id}", operation_id="crews_delete", status_code=204)
async def crews_delete(
    crew_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("write:actors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> Response:
    if not await storage.manual_crew_exists(crew_id):
        raise ResourceNotFound("crew")
    await storage.delete_manual_crew(crew_id)
    return Response(status_code=204)
