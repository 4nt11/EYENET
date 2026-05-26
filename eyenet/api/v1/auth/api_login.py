# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/login — exchange username/password for JWT pair."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from eyenet.api.auth import (
    REFRESH_TTL,
    load_signing_keypair,
    mint_access_token,
    mint_refresh_secret,
    verify_password,
)
from eyenet.api.deps import AuthError, get_audit, get_storage
from eyenet.api.v1.schemas.auth import LoginRequest, TokenPair
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])

_LOGIN_FAILURE_FLOOR_SECONDS = 0.2


@router.post(
    "/auth/login",
    operation_id="auth_login",
    response_model=TokenPair,
    status_code=200,
)
async def auth_login(
    body: LoginRequest,
    request: Request,
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> TokenPair:
    now = datetime.now(tz=UTC)
    user = await storage.get_system_user_by_username(body.username)
    credential = await storage.get_credential(user.id) if user is not None else None

    if user is None or not user.is_active or credential is None:
        user_id = user.id if user is not None else None
        await _reject(audit, reason="unknown_or_inactive", user_id=user_id, username=body.username)
        raise AuthError("login_failed")

    if not verify_password(body.password, credential.password_hash):
        await _reject(audit, reason="wrong_password", user_id=user.id, username=body.username)
        raise AuthError("login_failed")

    data_dir = request.app.state.data_dir
    signing_key = load_signing_keypair(data_dir)
    access_token, claims = mint_access_token(user_id=user.id, signing_key=signing_key, now=now)
    refresh_secret, refresh_hash = mint_refresh_secret()
    refresh_expires_at = now + REFRESH_TTL
    refresh_row = await storage.create_refresh_token(
        user_id=user.id,
        hash_value=refresh_hash,
        issued_at=now,
        expires_at=refresh_expires_at,
    )
    await storage.record_system_user_login(user_id=user.id, at=now)

    await audit.emit(
        event="eyenet.audit.auth.login.success",
        subject_kind="system_user",
        subject_id=user.id,
        system_user_id=user.id,
        payload={
            "username": body.username,
            "jti": str(claims.jti),
            "refresh_token_id": str(refresh_row.token_id),
        },
    )
    return TokenPair(
        access_token=access_token,
        access_expires_at=claims.expires_at,
        refresh_token=refresh_secret,
        refresh_expires_at=refresh_expires_at,
    )


async def _reject(
    audit: AuditEmitter,
    *,
    reason: str,
    user_id: UUID | None,
    username: str,
) -> None:
    await audit.emit(
        event="eyenet.audit.auth.login.failure",
        subject_kind="system_user",
        subject_id=user_id,
        system_user_id=user_id,
        payload={"username": username, "reason": reason},
    )
    await asyncio.sleep(_LOGIN_FAILURE_FLOOR_SECONDS)
