# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/auth/mfa — disable MFA after primary-factor re-auth.

Requires both a valid bearer token AND ``current_password`` in the body.
Proves the disabling caller still holds the primary factor — defeats
"attacker steals laptop, leaves MFA off" via a stolen session alone.

API_PLAN §M9.A3.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from eyenet.api.auth import verify_password
from eyenet.api.deps import AuthError, CurrentUser, get_audit, get_current_user, get_storage
from eyenet.api.v1.schemas.mfa import MfaDisableRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])

_REJECT_FLOOR_SECONDS = 0.2


@router.delete(
    "/auth/mfa",
    operation_id="auth_mfa_disable",
    status_code=204,
    response_class=Response,
)
async def auth_mfa_disable(
    body: MfaDisableRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> Response:
    credential = await storage.get_credential(current_user.user_id)
    if credential is None:
        await asyncio.sleep(_REJECT_FLOOR_SECONDS)
        raise AuthError("credential_missing")

    if not verify_password(body.current_password, credential.password_hash):
        await audit.emit(
            event="eyenet.audit.auth.mfa.disable_failed",
            subject_kind="system_user",
            subject_id=current_user.user_id,
            system_user_id=current_user.user_id,
            payload={"username": current_user.username, "reason": "wrong_password"},
        )
        await asyncio.sleep(_REJECT_FLOOR_SECONDS)
        raise AuthError("mfa_disable_wrong_password")

    await storage.put_credential(
        user_id=current_user.user_id,
        password_hash=credential.password_hash,
        password_updated_at=credential.password_updated_at,
        mfa_secret_encrypted=None,
    )
    await audit.emit(
        event="eyenet.audit.auth.mfa.disabled",
        subject_kind="system_user",
        subject_id=current_user.user_id,
        system_user_id=current_user.user_id,
        payload={"username": current_user.username},
    )
    return Response(status_code=204)
