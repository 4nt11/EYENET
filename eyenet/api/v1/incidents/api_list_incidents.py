# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/incidents — the operator triage feed (recent classified incidents).

Gated behind ``read:incidents``. Returns the most recently classified incidents, newest
first; ``label`` repeats to filter to one OR MORE taxonomy heads (OR), and ``q``
free-text-matches the message body (FTS5 on SQLite, LIKE fallback elsewhere). This is the
polling view; the
live view is the SSE stream, and each incident is also emitted on the bus as it fires.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.incidents import IncidentGroupOut, IncidentOut, IncidentSourceOut
from eyenet.contracts.incident import IncidentLabelRow, IncidentRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["incidents"])


@router.get("/incidents", operation_id="list_incidents", response_model=list[IncidentOut])
async def list_incidents(
    _: Annotated[CurrentUser, Depends(RequireScope("read:incidents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    label: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=256)] = None,
    group_id: Annotated[list[UUID] | None, Query()] = None,
    source_id: Annotated[list[UUID] | None, Query()] = None,
) -> list[IncidentOut]:
    # ?label= repeats (OR); ?group_id= / ?source_id= repeat to show only those groups/sources.
    rows = cast(
        "list[IncidentRow]",
        await storage.recent_incidents(
            limit=limit, labels=label, offset=offset, q=q, group_ids=group_id, source_ids=source_id
        ),
    )
    ids = [r.message_id for r in rows]
    bodies = await storage.bodies_by_message_ids(ids)
    ctx = await storage.message_context_by_ids(ids)  # (group_title, group_id, actor_id, handle)
    corrections = cast(
        "dict[UUID, IncidentLabelRow]", await storage.incident_labels_by_message_ids(ids)
    )
    return [
        IncidentOut(
            message_id=r.message_id,
            body=bodies.get(r.message_id),
            group=(mc := ctx.get(r.message_id, (None, None, None, None)))[0],
            group_id=mc[1],
            actor_id=mc[2],
            actor_handle=mc[3],
            labels=r.labels,
            scores=r.scores,
            model_version=r.model_version,
            classified_at=r.classified_at,
            corrected_labels=c.labels if (c := corrections.get(r.message_id)) else None,
            corrected_by=c.decided_by if c else None,
            corrected_at=c.decided_at if c else None,
        )
        for r in rows
    ]


@router.get(
    "/incidents/groups",
    operation_id="list_incident_groups",
    response_model=list[IncidentGroupOut],
)
async def list_incident_groups(
    _: Annotated[CurrentUser, Depends(RequireScope("read:incidents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> list[IncidentGroupOut]:
    """Every group that has incidents, noisiest first — the full option set for the feed's
    group filter (independent of the ``/incidents`` window)."""
    rows = await storage.incident_groups()
    return [IncidentGroupOut(group_id=gid, title=title, count=n) for gid, title, n in rows]


@router.get(
    "/incidents/sources",
    operation_id="list_incident_sources",
    response_model=list[IncidentSourceOut],
)
async def list_incident_sources(
    _: Annotated[CurrentUser, Depends(RequireScope("read:incidents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> list[IncidentSourceOut]:
    """Every source that has incidents, noisiest first — the source-level feed filter
    (a forum's incidents roll up under one source instead of thousands of threads)."""
    rows = await storage.incident_sources()
    return [IncidentSourceOut(source_id=sid, title=title, count=n) for sid, title, n in rows]
