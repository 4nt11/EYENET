"""POST /v1/auth/login — exchange username/password for JWT pair."""

from __future__ import annotations

from fastapi import APIRouter

from eyenet.api.v1.schemas.auth import LoginRequest, TokenPair

router = APIRouter(tags=["auth"])


@router.post("/auth/login", operation_id="auth_login", response_model=TokenPair, status_code=200)
async def auth_login(body: LoginRequest) -> TokenPair:
    raise NotImplementedError("auth_login (M9.0 skeleton)")
