"""POST /v1/auth/tokens — mint a new PAT for the caller."""

from __future__ import annotations

from fastapi import APIRouter, Header

from eyenet.api.v1.schemas.auth import PATMinted, PATMintRequest

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/tokens",
    operation_id="auth_mint_token",
    response_model=PATMinted,
    status_code=201,
)
async def auth_mint_token(
    body: PATMintRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> PATMinted:
    raise NotImplementedError("auth_mint_token (M9.0 skeleton)")
