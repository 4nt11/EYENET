"""POST /v1/attachments/{blob_id}/access — acknowledged binary fetch (§5.6 step 2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from eyenet.api.v1.schemas.attachments import FileAccessAcknowledgment

router = APIRouter(tags=["attachments"])


@router.post(
    "/attachments/{blob_id}/access",
    operation_id="attachments_access",
    response_class=StreamingResponse,
    status_code=200,
)
async def attachments_access(
    blob_id: UUID,
    body: FileAccessAcknowledgment,
) -> StreamingResponse:
    raise NotImplementedError("attachments_access (M9.0 skeleton)")
