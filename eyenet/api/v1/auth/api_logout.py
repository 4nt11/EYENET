# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/logout — deny the current access JWT + revoke the presented refresh."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from eyenet.api.auth import AuthCache, hash_refresh_secret
from eyenet.api.deps import (
    AuthError,
    CurrentUser,
    get_audit,
    get_auth_cache,
    get_current_user,
    get_storage,
)
from eyenet.api.v1.schemas.auth import LogoutRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/logout",
    operation_id="auth_logout",
    status_code=204,
    response_class=Response,
)
async def auth_logout(
    body: LogoutRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    cache: Annotated[AuthCache, Depends(get_auth_cache)],
) -> Response:
    # Logout denylists an interactive access JWT. A PAT principal carries no
    # jti (and no JWT expiry) — it cannot denylist a session; revoke it via
    # DELETE /v1/auth/tokens/{token_id} instead.
    if current_user.jti is None or current_user.token_expires_at is None:
        raise AuthError("pat_cannot_logout")

    now = datetime.now(tz=UTC)
    await storage.deny_jwt(
        jti=current_user.jti,
        user_id=current_user.user_id,
        denied_at=now,
        expires_at=current_user.token_expires_at,
    )

    revoked_refresh_id = None
    if body.refresh_token is not None:
        presented_hash = hash_refresh_secret(body.refresh_token)
        existing = await storage.get_refresh_token_by_hash(presented_hash)
        if (
            existing is not None
            and existing.revoked_at is None
            and existing.user_id == current_user.user_id
        ):
            await storage.revoke_refresh_token(token_id=existing.token_id, revoked_at=now)
            revoked_refresh_id = existing.token_id

    cache.invalidate(current_user.user_id)

    await audit.emit(
        event="eyenet.audit.auth.logout",
        subject_kind="system_user",
        subject_id=current_user.user_id,
        system_user_id=current_user.user_id,
        payload={
            "jti": str(current_user.jti),
            "refresh_token_id": str(revoked_refresh_id) if revoked_refresh_id else None,
        },
    )
    return Response(status_code=204)
