# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/login/verify — complete the MFA challenge issued by /login.

No bearer auth — the ``mfa_challenge_id`` IS the authentication context.
Lockout: 5 failed verify attempts within 15 minutes silently reuses the
401 surface (see plan §"Lockout"); the audit row carries
``mfa.locked_out`` for operator visibility.

API_PLAN §M9.A3.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Request

from eyenet.api.auth import (
    REFRESH_TTL,
    MfaKeyError,
    decrypt_secret,
    load_signing_keypair,
    mint_access_token,
    mint_refresh_secret,
    verify_code,
)
from eyenet.api.deps import AuthError, get_audit, get_mfa_key, get_storage
from eyenet.api.v1.schemas.auth import TokenPair
from eyenet.api.v1.schemas.mfa import MfaLoginVerifyRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])

_MFA_FAILURE_FLOOR_SECONDS = 0.2
_LOCKOUT_THRESHOLD: Final[int] = 5
_LOCKOUT_WINDOW: Final[timedelta] = timedelta(minutes=15)


@router.post(
    "/auth/login/verify",
    operation_id="auth_login_verify",
    response_model=TokenPair,
    status_code=200,
)
async def auth_login_verify(
    body: MfaLoginVerifyRequest,
    request: Request,
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    mfa_key: Annotated[Fernet, Depends(get_mfa_key)],
) -> TokenPair:
    now = datetime.now(tz=UTC)
    challenge = await storage.get_mfa_challenge(body.mfa_challenge_id)
    if challenge is None:
        await asyncio.sleep(_MFA_FAILURE_FLOOR_SECONDS)
        raise AuthError("mfa_unknown_challenge")

    user_id = challenge.user_id

    # Lockout window check — uniform 401 either way.
    failures = await storage.count_recent_mfa_failures(
        user_id=user_id,
        since=now - _LOCKOUT_WINDOW,
    )
    if failures >= _LOCKOUT_THRESHOLD:
        await audit.emit(
            event="eyenet.audit.auth.mfa.locked_out",
            subject_kind="system_user",
            subject_id=user_id,
            system_user_id=user_id,
            payload={
                "mfa_challenge_id": str(body.mfa_challenge_id),
                "recent_failures": failures,
            },
        )
        await asyncio.sleep(_MFA_FAILURE_FLOOR_SECONDS)
        raise AuthError("mfa_locked_out")

    if challenge.consumed_at is not None:
        await audit.emit(
            event="eyenet.audit.auth.mfa.replay_attempt",
            subject_kind="system_user",
            subject_id=user_id,
            system_user_id=user_id,
            payload={"mfa_challenge_id": str(body.mfa_challenge_id)},
        )
        await asyncio.sleep(_MFA_FAILURE_FLOOR_SECONDS)
        raise AuthError("mfa_challenge_replayed")

    if challenge.expires_at < now:
        await asyncio.sleep(_MFA_FAILURE_FLOOR_SECONDS)
        raise AuthError("mfa_challenge_expired")

    credential = await storage.get_credential(user_id)
    if credential is None or credential.mfa_secret_encrypted is None:
        # User disabled MFA between challenge issue and verify — bail.
        await asyncio.sleep(_MFA_FAILURE_FLOOR_SECONDS)
        raise AuthError("mfa_not_enrolled")

    try:
        secret = decrypt_secret(mfa_key, credential.mfa_secret_encrypted)
    except MfaKeyError as exc:
        # Tampered ciphertext or wrong mfa_key — same 401 surface.
        await asyncio.sleep(_MFA_FAILURE_FLOOR_SECONDS)
        raise AuthError("mfa_secret_unreadable") from exc

    if not verify_code(secret_b32=secret, code=body.code, now=now):
        await storage.bump_mfa_challenge_failures(body.mfa_challenge_id)
        await audit.emit(
            event="eyenet.audit.auth.mfa.verify_failed",
            subject_kind="system_user",
            subject_id=user_id,
            system_user_id=user_id,
            payload={"mfa_challenge_id": str(body.mfa_challenge_id)},
        )
        await asyncio.sleep(_MFA_FAILURE_FLOOR_SECONDS)
        raise AuthError("mfa_bad_code")

    # Code OK — consume challenge, mint pair.
    await storage.consume_mfa_challenge(
        challenge_id=body.mfa_challenge_id,
        consumed_at=now,
    )

    data_dir = request.app.state.data_dir
    signing_key = load_signing_keypair(data_dir)
    access_token, claims = mint_access_token(user_id=user_id, signing_key=signing_key, now=now)
    refresh_secret, refresh_hash = mint_refresh_secret()
    refresh_expires_at = now + REFRESH_TTL
    refresh_row = await storage.create_refresh_token(
        user_id=user_id,
        hash_value=refresh_hash,
        issued_at=now,
        expires_at=refresh_expires_at,
    )
    await storage.record_system_user_login(user_id=user_id, at=now)

    await audit.emit(
        event="eyenet.audit.auth.mfa.verified",
        subject_kind="system_user",
        subject_id=user_id,
        system_user_id=user_id,
        payload={
            "mfa_challenge_id": str(body.mfa_challenge_id),
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
