# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/refresh — rotate refresh token, mint a new access token.

Refresh always rotates: the old row is revoked with ``replaced_by``
pointing at the new row. A second use of the same secret hits a revoked
row and is rejected — that's the replay-detection signal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from eyenet.api.auth import (
    REFRESH_TTL,
    hash_refresh_secret,
    load_signing_keypair,
    mint_access_token,
    mint_refresh_secret,
)
from eyenet.api.deps import AuthError, get_audit, get_storage
from eyenet.api.v1.schemas.auth import RefreshRequest, TokenPair
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/refresh",
    operation_id="auth_refresh",
    response_model=TokenPair,
    status_code=200,
)
async def auth_refresh(
    body: RefreshRequest,
    request: Request,
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> TokenPair:
    now = datetime.now(tz=UTC)
    presented_hash = hash_refresh_secret(body.refresh_token)
    existing = await storage.get_refresh_token_by_hash(presented_hash)
    if existing is None or existing.revoked_at is not None or existing.expires_at <= now:
        raise AuthError("invalid_refresh")

    user = await storage.get_system_user_by_id(existing.user_id)
    if user is None or not user.is_active:
        raise AuthError("user_inactive")

    signing_key = load_signing_keypair(request.app.state.data_dir)
    access_token, claims = mint_access_token(user_id=user.id, signing_key=signing_key, now=now)
    new_secret, new_hash = mint_refresh_secret()
    refresh_expires_at = now + REFRESH_TTL
    new_row = await storage.create_refresh_token(
        user_id=user.id,
        hash_value=new_hash,
        issued_at=now,
        expires_at=refresh_expires_at,
    )
    await storage.revoke_refresh_token(
        token_id=existing.token_id,
        revoked_at=now,
        replaced_by=new_row.token_id,
    )

    await audit.emit(
        event="eyenet.audit.auth.refresh",
        subject_kind="system_user",
        subject_id=user.id,
        system_user_id=user.id,
        payload={
            "previous_refresh_token_id": str(existing.token_id),
            "refresh_token_id": str(new_row.token_id),
            "jti": str(claims.jti),
        },
    )
    return TokenPair(
        access_token=access_token,
        access_expires_at=claims.expires_at,
        refresh_token=new_secret,
        refresh_expires_at=refresh_expires_at,
    )
