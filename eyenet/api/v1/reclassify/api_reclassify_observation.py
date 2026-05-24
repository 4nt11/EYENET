"""POST /v1/observations/{observation_id}/reclassify — §4.9 promotion."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.reclassify import ReclassificationRequest, ReclassificationResult

router = APIRouter(tags=["reclassify"])


@router.post(
    "/observations/{observation_id}/reclassify",
    operation_id="observations_reclassify",
    response_model=ReclassificationResult,
    status_code=200,
)
async def observations_reclassify(
    observation_id: UUID,
    body: ReclassificationRequest,
) -> ReclassificationResult:
    raise NotImplementedError("observations_reclassify (M9.0 skeleton)")
