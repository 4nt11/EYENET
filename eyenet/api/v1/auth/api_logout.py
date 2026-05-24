"""POST /v1/auth/logout — revoke the current refresh token + denylist the access JWT."""

from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter(tags=["auth"])


@router.post("/auth/logout", operation_id="auth_logout", status_code=204, response_class=Response)
async def auth_logout() -> Response:
    raise NotImplementedError("auth_logout (M9.0 skeleton)")
