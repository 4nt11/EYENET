# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/cases — list cases visible to caller (§4.10.4 predicate).

``admin:case`` holders see every case; everyone else sees only cases they
actively collaborate on (the list-visibility predicate, enforced in storage
via ``collaborator_user_id``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.cases._detail import has_admin_case, to_case_summary
from eyenet.api.v1.schemas.cases import CursorPageCaseSummary
from eyenet.api.v1.schemas.enums import CaseStatus
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["cases"])


@router.get(
    "/cases",
    operation_id="cases_list",
    response_model=CursorPageCaseSummary,
    status_code=200,
)
async def cases_list(
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    status: Annotated[CaseStatus | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> CursorPageCaseSummary:
    visibility = None if has_admin_case(current_user) else current_user.user_id
    rows = await storage.list_cases(
        status=status,
        since=since,
        until=until,
        collaborator_user_id=visibility,
        limit=page.fetch_limit,
        offset=page.offset,
    )
    estimated_total = (
        await storage.count_cases(
            status=status, since=since, until=until, collaborator_user_id=visibility
        )
        if page.include_total
        else None
    )
    return CursorPageCaseSummary(
        items=[to_case_summary(r) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
