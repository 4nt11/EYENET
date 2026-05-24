"""GET /v1/audit — paginated audit log."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.audit import CursorPageAuditRow

router = APIRouter(tags=["audit"])


@router.get(
    "/audit",
    operation_id="audit_list",
    response_model=CursorPageAuditRow,
    status_code=200,
)
async def audit_list(
    subject: str | None = Query(default=None, max_length=128),
    user_id: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = Query(default=False),
) -> CursorPageAuditRow:
    raise NotImplementedError("audit_list (M9.0 skeleton)")
