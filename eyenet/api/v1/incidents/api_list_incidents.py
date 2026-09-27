# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/incidents — the operator triage feed (recent classified incidents).

Gated behind ``read:incidents``. Returns the most recently classified incidents, newest
first; optional ``label`` filters to one taxonomy head. This is the polling view; the
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
    label: Annotated[str | None, Query()] = None,
) -> list[IncidentOut]:
    rows = cast("list[IncidentRow]", await storage.recent_incidents(limit=limit))
    ids = [r.message_id for r in rows]
    bodies = await storage.bodies_by_message_ids(ids)
    corrections = cast(
        "dict[UUID, IncidentLabelRow]", await storage.incident_labels_by_message_ids(ids)
    )
    out = [
        IncidentOut(
            message_id=r.message_id,
            body=bodies.get(r.message_id),
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
    if label is not None:
        out = [i for i in out if label in i.labels]
    return out
