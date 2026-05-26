# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/mfa/enroll — mint a fresh TOTP secret (not persisted yet).

The client renders the provisioning URI as a QR code, scans into an
authenticator app, then echoes ``secret_b32`` + the first generated code
back via ``POST /v1/auth/mfa/verify-enroll`` to commit the encrypted
secret to storage (API_PLAN §M9.A3).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.auth import generate_secret, provisioning_uri
from eyenet.api.deps import CurrentUser, get_current_user
from eyenet.api.v1.schemas.mfa import MfaEnrollResponse

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/mfa/enroll",
    operation_id="auth_mfa_enroll",
    response_model=MfaEnrollResponse,
    status_code=200,
)
async def auth_mfa_enroll(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> MfaEnrollResponse:
    secret_b32 = generate_secret()
    uri = provisioning_uri(secret_b32=secret_b32, username=current_user.username)
    return MfaEnrollResponse(provisioning_uri=uri, secret_b32=secret_b32)
