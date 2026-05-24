"""POST /v1/linkages/{linkage_id}/confirm — operator decision: CONFIRMED."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header

from eyenet.api.v1.schemas.linkages import LinkageDecisionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted

router = APIRouter(tags=["linkages"])


@router.post(
    "/linkages/{linkage_id}/confirm",
    operation_id="linkages_confirm",
    response_model=WriteAccepted,
    status_code=202,
)
async def linkages_confirm(
    linkage_id: UUID,
    body: LinkageDecisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> WriteAccepted:
    raise NotImplementedError("linkages_confirm (M9.0 skeleton)")
