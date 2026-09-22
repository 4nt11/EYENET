# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/cases/{case_id}/observations — case-scoped evidence observations.

Direct-membership semantics (§4.10.1): returns only observations explicitly
added to the case via ``case_member`` (``subject_kind=observation``, not
removed) — NOT every observation of the case's actors. ``read:observations``
scope AND case visibility are both required (a non-collaborator gets 404, no
existence oracle — see :func:`require_case_visible`).
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.cases._detail import require_case_visible
from eyenet.api.v1.schemas.actors import CursorPageObservationSummary, ObservationSummary
from eyenet.models.observation import ObservationTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}/observations",
    operation_id="cases_list_observations",
    response_model=CursorPageObservationSummary,
    status_code=200,
)
async def cases_list_observations(
    case_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:observations"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
) -> CursorPageObservationSummary:
    await require_case_visible(storage, case_id, current_user)
    rows = cast(
        "list[ObservationTable]",
        await storage.list_observations_for_case(
            case_id, limit=page.fetch_limit, offset=page.offset
        ),
    )
    estimated_total = (
        await storage.count_observations_for_case(case_id) if page.include_total else None
    )
    return CursorPageObservationSummary(
        items=[ObservationSummary.from_domain(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
