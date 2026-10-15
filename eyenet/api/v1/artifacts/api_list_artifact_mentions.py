# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/artifacts/{artifact_id}/mentions — the 'mentioned by' drill-down.

One row per sighting (newest first): the message, the actor (handle + display
name), the group, the source, when it was seen, and the char offset. This is the
who / where / when behind the counts on the browse row.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.artifacts import ArtifactMention, CursorPageArtifactMention
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["artifacts"])


@router.get(
    "/artifacts/{artifact_id}/mentions",
    operation_id="artifacts_list_mentions",
    response_model=CursorPageArtifactMention,
    status_code=200,
)
async def artifacts_list_mentions(
    artifact_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:search"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPageArtifactMention:
    if await storage.get_infrastructure_artifact(artifact_id) is None:
        raise ResourceNotFound("infrastructure_artifact")
    rows = await storage.list_artifact_mentions(
        artifact_id, limit=page.fetch_limit, offset=page.offset
    )
    estimated_total = (
        await storage.count_artifact_mentions(artifact_id) if page.include_total else None
    )
    items = [
        ArtifactMention(
            message_id=mid,
            actor_id=aid,
            actor_handle=handle,
            actor_display_name=display,
            group_id=gid,
            group_title=title,
            source_id=sid,
            ts=ts,
            char_offset=off,
        )
        for mid, aid, handle, display, gid, title, sid, ts, off in rows[: page.limit]
    ]
    return CursorPageArtifactMention(
        items=items,
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
