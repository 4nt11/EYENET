"""POST /v1/identities/{name}/release — release a claimed identity (M9.0 stub)."""

from __future__ import annotations

from fastapi import APIRouter, Header, Path

from eyenet.api.v1.schemas.identities import IdentityActionRequest
from eyenet.api.v1.schemas.writes import WriteAccepted

router = APIRouter(tags=["identities"])


@router.post(
    "/identities/{identity_id}/release",
    operation_id="identities_release",
    response_model=WriteAccepted,
    status_code=202,
)
async def identities_release(
    body: IdentityActionRequest,
    identity_id: str = Path(..., min_length=1, max_length=128),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> WriteAccepted:
    raise NotImplementedError("identities_release (M9.0 skeleton)")
