# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/identities/qr-login — start a QR login (mint a user session in-UI).

Admin-gated (same as the upload provision). Opens a live Telethon client, mints
the first QR, and parks it in the process-local registry keyed by the returned
``login_id``. The caller renders ``qr_url`` as a QR, then polls
``GET /v1/identities/qr-login/{login_id}`` and, if 2FA is set, POSTs the password.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError

from eyenet.api.auth._qr_login import QrLoginRegistry
from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    ScopeForbidden,
    get_qr_logins,
    get_storage,
)
from eyenet.api.v1.schemas.qr_login import QrLoginChallenge, QrLoginStartRequest
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["identities"])


@router.post(
    "/identities/qr-login",
    operation_id="identities_qr_start",
    response_model=QrLoginChallenge,
    status_code=201,
)
async def identities_qr_start(
    body: QrLoginStartRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    registry: Annotated[QrLoginRegistry, Depends(get_qr_logins)],
) -> QrLoginChallenge:
    if current_user.role != SystemUserRole.ADMIN:
        raise ScopeForbidden("admin (identity provisioning is admin-only)")

    source = await storage.get_source(body.source_id)
    if not isinstance(source, SourceRow):
        raise ResourceNotFound("source")
    if SourceKind(source.kind) != SourceKind.TELEGRAM:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "source_id"),
                    "msg": "QR login is only supported for Telegram sources",
                    "type": "value_error",
                }
            ]
        )

    source_config: dict[str, object] = {
        "telegram_api_id": body.telegram_api_id,
        "telegram_api_hash": body.telegram_api_hash,
        "monitor_groups": list(body.monitor_groups),
    }
    state = await registry.start(
        user_id=current_user.user_id,
        api_id=body.telegram_api_id,
        api_hash=body.telegram_api_hash,
        name=body.name,
        source_id=body.source_id,
        source_config=source_config,
        role=body.role,
        cooldown_seconds=body.cooldown_seconds,
        proxy_uri=body.proxy_uri,
        notes=body.notes,
    )
    return QrLoginChallenge(
        login_id=state.login_id,
        qr_url=state.qr_url,
        expires_at=state.expires_at,
        status=state.status.value,
    )
