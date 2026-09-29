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
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.incidents import (
    CursorPageIncidentOut,
    IncidentCountryOut,
    IncidentGroupOut,
    IncidentOut,
    IncidentSourceOut,
)
from eyenet.contracts.incident import IncidentLabelRow, IncidentRow, MessageGeoRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["incidents"])


@router.get("/incidents", operation_id="list_incidents", response_model=CursorPageIncidentOut)
async def list_incidents(
    _: Annotated[CurrentUser, Depends(RequireScope("read:incidents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    label: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=256)] = None,
    group_id: Annotated[list[UUID] | None, Query()] = None,
    source_id: Annotated[list[UUID] | None, Query()] = None,
    victim_country: Annotated[list[str] | None, Query(min_length=2, max_length=2)] = None,
) -> CursorPageIncidentOut:
    # ?label= repeats (OR); ?group_id= / ?source_id= repeat to show only those groups/sources.
    # ?victim_country= repeats (ISO alpha-2) to show only incidents with that geo verdict —
    # the "show me CL incidents" filter (?q= is a body search and never matched the verdict).
    # Bodyless incidents (pure-quote forum posts that strip to empty and classify into
    # content-less "row not retained" rows) are dropped IN SQL via exclude_bodyless, so the
    # page returns `limit` real rows and estimated_total counts the same set — no post-fetch
    # trimming that would make the page shorter than requested or the total overcount.
    rows = cast(
        "list[IncidentRow]",
        await storage.recent_incidents(
            limit=page.fetch_limit,  # over-fetch by one to detect a further page
            labels=label,
            offset=page.offset,
            q=q,
            group_ids=group_id,
            source_ids=source_id,
            victim_countries=victim_country,
            exclude_bodyless=True,
        ),
    )
    next_cursor = page.next_cursor(fetched=len(rows))
    page_rows = rows[: page.limit]
    ids = [r.message_id for r in page_rows]
    bodies = await storage.bodies_by_message_ids(ids)
    ctx = await storage.message_context_by_ids(ids)  # (group_title, group_id, actor_id, handle)
    corrections = cast(
        "dict[UUID, IncidentLabelRow]", await storage.incident_labels_by_message_ids(ids)
    )
    geo = cast("dict[UUID, MessageGeoRow]", await storage.message_geo_by_message_ids(ids))
    country_by_id = {mid: g.country for mid, g in geo.items()}
    estimated_total = (
        await storage.count_incidents(
            labels=label,
            q=q,
            group_ids=group_id,
            source_ids=source_id,
            victim_countries=victim_country,
            exclude_bodyless=True,
        )
        if page.include_total
        else None
    )
    items = [
        IncidentOut(
            message_id=r.message_id,
            body=bodies.get(r.message_id),
            group=(mc := ctx.get(r.message_id, (None, None, None, None)))[0],
            group_id=mc[1],
            actor_id=mc[2],
            actor_handle=mc[3],
            victim_country=country_by_id.get(r.message_id),
            labels=r.labels,
            scores=r.scores,
            model_version=r.model_version,
            classified_at=r.classified_at,
            corrected_labels=c.labels if (c := corrections.get(r.message_id)) else None,
            corrected_by=c.decided_by if c else None,
            corrected_at=c.decided_at if c else None,
        )
        for r in page_rows
    ]
    return CursorPageIncidentOut(
        items=items, next_cursor=next_cursor, estimated_total=estimated_total
    )


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
    return [
        IncidentGroupOut(group_id=gid, title=title, source_id=sid, count=n)
        for gid, title, sid, n in rows
    ]


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


@router.get(
    "/incidents/countries",
    operation_id="list_incident_countries",
    response_model=list[IncidentCountryOut],
)
async def list_incident_countries(
    _: Annotated[CurrentUser, Depends(RequireScope("read:incidents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> list[IncidentCountryOut]:
    """Every resolved victim country in the incident feed, noisiest first — the option set
    for the victim-country filter (ISO alpha-2; mixed/unknown verdicts excluded)."""
    rows = await storage.incident_countries()
    return [IncidentCountryOut(country=c, count=n) for c, n in rows]
