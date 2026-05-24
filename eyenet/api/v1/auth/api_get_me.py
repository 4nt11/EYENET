"""GET /v1/auth/me — current user profile + scopes."""

from __future__ import annotations

from fastapi import APIRouter

from eyenet.api.v1.schemas.auth import UserMe

router = APIRouter(tags=["auth"])


@router.get("/auth/me", operation_id="auth_me", response_model=UserMe, status_code=200)
async def auth_me() -> UserMe:
    raise NotImplementedError("auth_me (M9.0 skeleton)")
