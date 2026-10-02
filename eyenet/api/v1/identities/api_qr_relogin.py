# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/identities/{identity_id}/qr-login — re-login an EXISTING Telegram identity.

The QR twin of PUT .../session: instead of uploading a fresh credential, mint one
live by scanning a QR, and swap it onto the existing identity. Reuses the identity's
own api_id/api_hash (from source_config) + name/source/pacing — nothing but the
session changes. Polling + 2FA use the same qr-login/{login_id} endpoints.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

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
from eyenet.api.v1.schemas.qr_login import QrLoginChallenge
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["identities"])


def _require(cfg: dict[str, object], key: str) -> object:
    val = cfg.get(key)
    if val is None:
        raise RequestValidationError(
            [
                {
                    "loc": ("path", "identity_id"),
                    "msg": f"identity's source_config is missing {key}; cannot re-login via QR",
                    "type": "value_error",
                }
            ]
        )
    return val


@router.post(
    "/identities/{identity_id}/qr-login",
    operation_id="identities_qr_relogin",
    response_model=QrLoginChallenge,
    status_code=201,
)
async def identities_qr_relogin(
    identity_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    registry: Annotated[QrLoginRegistry, Depends(get_qr_logins)],
) -> QrLoginChallenge:
    if current_user.role != SystemUserRole.ADMIN:
        raise ScopeForbidden("admin (identity credential rotation is admin-only)")

    identity = await storage.get_identity(identity_id)
    if identity is None:
        raise ResourceNotFound("identity")
    source = await storage.get_source(identity.source_id)
    if not isinstance(source, SourceRow):
        raise ResourceNotFound("source")
    if SourceKind(source.kind) != SourceKind.TELEGRAM:
        raise RequestValidationError(
            [
                {
                    "loc": ("path", "identity_id"),
                    "msg": "QR login is only supported for Telegram identities",
                    "type": "value_error",
                }
            ]
        )

    cfg = identity.source_config or {}
    api_id = int(_require(cfg, "telegram_api_id"))  # type: ignore[call-overload]
    api_hash = str(_require(cfg, "telegram_api_hash"))

    state = await registry.start(
        user_id=current_user.user_id,
        api_id=api_id,
        api_hash=api_hash,
        name=identity.name,
        source_id=identity.source_id,
        source_config=cfg,
        role=identity.role,
        cooldown_seconds=identity.cooldown_seconds,
        proxy_uri=identity.proxy_uri,
        notes=identity.notes,
        target_identity_id=identity_id,
    )
    return QrLoginChallenge(
        login_id=state.login_id,
        qr_url=state.qr_url,
        expires_at=state.expires_at,
        status=state.status.value,
    )
