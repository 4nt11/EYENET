"""POST /v1/auth/refresh — exchange refresh token for a new access token."""

from __future__ import annotations

from fastapi import APIRouter

from eyenet.api.v1.schemas.auth import AccessToken, RefreshRequest

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/refresh", operation_id="auth_refresh", response_model=AccessToken, status_code=200
)
async def auth_refresh(body: RefreshRequest) -> AccessToken:
    raise NotImplementedError("auth_refresh (M9.0 skeleton)")
