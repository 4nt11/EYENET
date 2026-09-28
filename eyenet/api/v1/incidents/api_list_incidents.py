# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/incidents — the operator triage feed (recent classified incidents).

Gated behind ``read:incidents``. Returns the most recently classified incidents, newest
first; optional ``label`` filters to one taxonomy head and ``q`` free-text-matches the
message body (FTS5 on SQLite, LIKE fallback elsewhere). This is the polling view; the
live view is the SSE stream, and each incident is also emitted on the bus as it fires.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.incidents import IncidentOut
from eyenet.contracts.incident import IncidentLabelRow, IncidentRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["incidents"])


@router.get("/incidents", operation_id="list_incidents", response_model=list[IncidentOut])
async def list_incidents(
    _: Annotated[CurrentUser, Depends(RequireScope("read:incidents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    label: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=256)] = None,
) -> list[IncidentOut]:
    rows = cast(
        "list[IncidentRow]",
        await storage.recent_incidents(limit=limit, label=label, offset=offset, q=q),
    )
    ids = [r.message_id for r in rows]
    bodies = await storage.bodies_by_message_ids(ids)
    ctx = await storage.message_context_by_ids(ids)  # (group_title, actor_id, actor_handle)
    corrections = cast(
        "dict[UUID, IncidentLabelRow]", await storage.incident_labels_by_message_ids(ids)
    )
    return [
        IncidentOut(
            message_id=r.message_id,
            body=bodies.get(r.message_id),
            group=(mc := ctx.get(r.message_id, (None, None, None)))[0],
            actor_id=mc[1],
            actor_handle=mc[2],
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
