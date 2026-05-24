"""POST /v1/attachments/{blob_id}/reclassify — §4.9 promotion."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.reclassify import ReclassificationRequest, ReclassificationResult

router = APIRouter(tags=["reclassify"])


@router.post(
    "/attachments/{blob_id}/reclassify",
    operation_id="attachments_reclassify",
    response_model=ReclassificationResult,
    status_code=200,
)
async def attachments_reclassify(
    blob_id: UUID,
    body: ReclassificationRequest,
) -> ReclassificationResult:
    raise NotImplementedError("attachments_reclassify (M9.0 skeleton)")
