# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/auth/me — current user profile + freshly resolved scopes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, get_current_user
from eyenet.api.v1.schemas.auth import UserMe

router = APIRouter(tags=["auth"])


@router.get(
    "/auth/me",
    operation_id="auth_me",
    response_model=UserMe,
    status_code=200,
)
async def auth_me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> UserMe:
    return UserMe(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role,
        scopes=sorted(current_user.effective_scopes),
    )
