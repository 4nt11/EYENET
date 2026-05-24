"""POST /v1/linkages/{linkage_id}/suspect — operator decision: SUSPECTED."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header

from eyenet.api.v1.schemas.linkages import LinkageDecisionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted

router = APIRouter(tags=["linkages"])


@router.post(
    "/linkages/{linkage_id}/suspect",
    operation_id="linkages_suspect",
    response_model=WriteAccepted,
    status_code=202,
)
async def linkages_suspect(
    linkage_id: UUID,
    body: LinkageDecisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> WriteAccepted:
    raise NotImplementedError("linkages_suspect (M9.0 skeleton)")
