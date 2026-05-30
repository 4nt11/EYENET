# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/audit — paginated, filterable audit log (M9.F4)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.deps_paging import CursorParams, cursor_params
from eyenet.api.v1.schemas.audit import AuditRow, CursorPageAuditRow
from eyenet.contracts.audit import AuditLogRow
from eyenet.models import AuditLogTable
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["audit"])


@router.get(
    "/audit",
    operation_id="audit_list",
    response_model=CursorPageAuditRow,
    status_code=200,
)
async def audit_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:audit"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    page: Annotated[CursorParams, Depends(cursor_params)],
    user: Annotated[UUID | None, Query()] = None,
    subject: Annotated[str | None, Query(max_length=256)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> CursorPageAuditRow:
    rows = cast(
        "list[AuditLogRow]",
        await storage.list_audit(
            since=since,
            until=until,
            user=user,
            subject=subject,
            limit=page.fetch_limit,
            offset=page.offset,
        ),
    )
    estimated_total = (
        await storage.count_audit(since=since, until=until, user=user, subject=subject)
        if page.include_total
        else None
    )
    return CursorPageAuditRow(
        items=[AuditRow.from_domain(cast("AuditLogTable", r)) for r in rows[: page.limit]],
        next_cursor=page.next_cursor(fetched=len(rows)),
        estimated_total=estimated_total,
    )
