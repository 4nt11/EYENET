"""DELETE /v1/auth/tokens/{token_id} — revoke a PAT."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

router = APIRouter(tags=["auth"])


@router.delete(
    "/auth/tokens/{token_id}",
    operation_id="auth_revoke_token",
    status_code=204,
    response_class=Response,
)
async def auth_revoke_token(token_id: UUID) -> Response:
    raise NotImplementedError("auth_revoke_token (M9.0 skeleton)")
