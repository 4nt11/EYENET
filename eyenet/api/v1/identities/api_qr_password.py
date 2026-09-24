# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/identities/qr-login/{login_id}/password — supply the 2FA password.

Admin-gated + owner-scoped. Valid only while the login is in ``password_needed``
(after the QR was scanned on a 2FA-protected account). The password is handed to
the waiting driver task via an in-memory event and is never persisted or logged.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.auth._qr_login import QrLoginRegistry
from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    ScopeForbidden,
    get_qr_logins,
)
from eyenet.api.v1.schemas.qr_login import QrLoginStatusResponse, QrPasswordRequest
from eyenet.contracts.enums import SystemUserRole

router = APIRouter(tags=["identities"])


@router.post(
    "/identities/qr-login/{login_id}/password",
    operation_id="identities_qr_password",
    response_model=QrLoginStatusResponse,
    status_code=200,
)
async def identities_qr_password(
    login_id: UUID,
    body: QrPasswordRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    registry: Annotated[QrLoginRegistry, Depends(get_qr_logins)],
) -> QrLoginStatusResponse:
    if current_user.role != SystemUserRole.ADMIN:
        raise ScopeForbidden("admin (identity provisioning is admin-only)")
    state = await registry.submit_password(
        login_id, owner=current_user.user_id, password=body.password
    )
    if state is None:
        raise ResourceNotFound("qr_login")
    return QrLoginStatusResponse(
        status=state.status.value,
        qr_url=state.qr_url,
        identity_id=state.identity_id,
        detail=state.error,
    )
