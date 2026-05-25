"""POST /v1/identities/freeze_all — freeze every identity in the pool (M9.0 stub)."""

from __future__ import annotations

from fastapi import APIRouter, Header

from eyenet.api.v1.schemas.identities import IdentityActionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted

router = APIRouter(tags=["identities"])


@router.post(
    "/identities/freeze_all",
    operation_id="identities_freeze_all",
    response_model=WriteAccepted,
    status_code=202,
)
async def identities_freeze_all(
    body: IdentityActionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> WriteAccepted:
    raise NotImplementedError("identities_freeze_all (M9.0 skeleton)")
