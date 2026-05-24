"""POST /v1/auth/stream-token — short-lived token for SSE EventSource (no header auth)."""

from __future__ import annotations

from fastapi import APIRouter

from eyenet.api.v1.schemas.auth import StreamTokenMinted, StreamTokenRequest

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/stream-token",
    operation_id="auth_mint_stream_token",
    response_model=StreamTokenMinted,
    status_code=200,
)
async def auth_mint_stream_token(body: StreamTokenRequest) -> StreamTokenMinted:
    raise NotImplementedError("auth_mint_stream_token (M9.0 skeleton)")
