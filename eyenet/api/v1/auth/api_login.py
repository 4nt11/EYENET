# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/login — exchange username/password for JWT pair OR MFA challenge.

If the credential row carries an ``mfa_secret_encrypted``, the server short-
circuits with a :class:`MfaLoginChallenge` (HTTP 200, ``mfa_required: true``).
The client must follow with ``POST /v1/auth/login/verify`` to complete the
second factor (API_PLAN §M9.A3).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final
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
from eyenet.api.v1.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MfaLoginChallenge,
    TokenPair,
)
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])

_LOGIN_FAILURE_FLOOR_SECONDS = 0.2
MFA_CHALLENGE_TTL: Final[timedelta] = timedelta(seconds=90)


@router.post(
    "/auth/login",
    operation_id="auth_login",
    response_model=LoginResponse,
    status_code=200,
)
async def auth_login(
    body: LoginRequest,
    request: Request,
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> LoginResponse:
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

    if credential.mfa_secret_encrypted is not None:
        challenge = await storage.create_mfa_challenge(
            user_id=user.id,
            issued_at=now,
            expires_at=now + MFA_CHALLENGE_TTL,
        )
        await audit.emit(
            event="eyenet.audit.auth.mfa.challenge_issued",
            subject_kind="system_user",
            subject_id=user.id,
            system_user_id=user.id,
            payload={
                "username": body.username,
                "mfa_challenge_id": str(challenge.challenge_id),
            },
        )
        return MfaLoginChallenge(mfa_challenge_id=challenge.challenge_id)

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
