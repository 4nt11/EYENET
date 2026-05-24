"""POST /v1/panic — instant kill-switch: stop collectors, freeze writes, page operator."""

from __future__ import annotations

from fastapi import APIRouter, Header

from eyenet.api.v1.schemas.identities import PanicRequest
from eyenet.api.v1.schemas.writes import WriteAccepted

router = APIRouter(tags=["control"])


@router.post(
    "/panic",
    operation_id="control_panic",
    response_model=WriteAccepted,
    status_code=202,
)
async def control_panic(
    body: PanicRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> WriteAccepted:
    raise NotImplementedError("control_panic (M9.0 skeleton)")
