"""GET /v1/audit/file-access/by-user — per-operator access history (§5.8)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.attachments import FileAccessExoneration

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/file-access/by-user",
    operation_id="audit_file_access_by_user",
    response_model=FileAccessExoneration,
    status_code=200,
)
async def audit_file_access_by_user(
    user_id: UUID = Query(...),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
) -> FileAccessExoneration:
    raise NotImplementedError("audit_file_access_by_user (M9.0 skeleton)")
