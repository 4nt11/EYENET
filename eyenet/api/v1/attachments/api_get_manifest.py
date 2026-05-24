"""GET /v1/attachments/{blob_id}/manifest — metadata only, no bytes (§5.6 step 1)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.attachments import FileManifest

router = APIRouter(tags=["attachments"])


@router.get(
    "/attachments/{blob_id}/manifest",
    operation_id="attachments_manifest",
    response_model=FileManifest,
    status_code=200,
)
async def attachments_manifest(blob_id: UUID) -> FileManifest:
    raise NotImplementedError("attachments_manifest (M9.0 skeleton)")
