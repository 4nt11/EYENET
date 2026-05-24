"""GET /v1/audit/file-access — signed exoneration record by content hash (§5.8)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.attachments import FileAccessExoneration

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/file-access",
    operation_id="audit_file_access_by_hash",
    response_model=FileAccessExoneration,
    status_code=200,
)
async def audit_file_access_by_hash(
    content_hash: str = Query(pattern=r"^[0-9a-f]{64}$"),
) -> FileAccessExoneration:
    raise NotImplementedError("audit_file_access_by_hash (M9.0 skeleton)")
