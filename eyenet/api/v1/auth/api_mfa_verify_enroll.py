# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/mfa/verify-enroll — confirm enrollment and persist encrypted secret.

Client echoes the ``secret_b32`` minted by ``/v1/auth/mfa/enroll`` along
with a fresh 6-digit code. The handler verifies the code against the
echoed secret BEFORE writing to storage — if the code is wrong, nothing
is persisted (the user can retry the whole enroll flow cleanly).

API_PLAN §M9.A3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Response

from eyenet.api.auth import encrypt_secret, verify_code
from eyenet.api.deps import (
    AuthError,
    CurrentUser,
    get_audit,
    get_current_user,
    get_mfa_key,
    get_storage,
)
from eyenet.api.v1.schemas.mfa import MfaVerifyEnrollRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/mfa/verify-enroll",
    operation_id="auth_mfa_verify_enroll",
    status_code=204,
    response_class=Response,
)
async def auth_mfa_verify_enroll(
    body: MfaVerifyEnrollRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    mfa_key: Annotated[Fernet, Depends(get_mfa_key)],
) -> Response:
    now = datetime.now(tz=UTC)

    if not verify_code(secret_b32=body.secret_b32, code=body.code, now=now):
        await audit.emit(
            event="eyenet.audit.auth.mfa.enroll_failed",
            subject_kind="system_user",
            subject_id=current_user.user_id,
            system_user_id=current_user.user_id,
            payload={"username": current_user.username},
        )
        raise AuthError("mfa_enroll_bad_code")

    credential = await storage.get_credential(current_user.user_id)
    if credential is None:
        raise AuthError("credential_missing")

    encrypted = encrypt_secret(mfa_key, body.secret_b32)
    await storage.put_credential(
        user_id=current_user.user_id,
        password_hash=credential.password_hash,
        password_updated_at=credential.password_updated_at,
        mfa_secret_encrypted=encrypted,
    )

    await audit.emit(
        event="eyenet.audit.auth.mfa.enrolled",
        subject_kind="system_user",
        subject_id=current_user.user_id,
        system_user_id=current_user.user_id,
        payload={"username": current_user.username},
    )
    return Response(status_code=204)
