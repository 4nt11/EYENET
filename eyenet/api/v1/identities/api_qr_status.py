# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/identities/qr-login/{login_id} — poll a QR login's status.

Admin-gated + owner-scoped (only the operator who started it can read it). The
``qr_url`` refreshes as the token is regenerated; on ``complete`` the
``identity_id`` is set; on ``error``/``expired`` ``detail`` gives a reason.
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
from eyenet.api.v1.schemas.qr_login import QrLoginStatusResponse
from eyenet.contracts.enums import SystemUserRole

router = APIRouter(tags=["identities"])


@router.get(
    "/identities/qr-login/{login_id}",
    operation_id="identities_qr_status",
    response_model=QrLoginStatusResponse,
    status_code=200,
)
async def identities_qr_status(
    login_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    registry: Annotated[QrLoginRegistry, Depends(get_qr_logins)],
) -> QrLoginStatusResponse:
    if current_user.role != SystemUserRole.ADMIN:
        raise ScopeForbidden("admin (identity provisioning is admin-only)")
    state = registry.get(login_id, owner=current_user.user_id)
    if state is None:
        raise ResourceNotFound("qr_login")
    return QrLoginStatusResponse(
        status=state.status.value,
        qr_url=state.qr_url,
        identity_id=state.identity_id,
        detail=state.error,
    )
