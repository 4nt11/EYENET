# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/auth/tokens/{token_id} — revoke a PAT (M9.A4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from eyenet.api.deps import (
    CurrentUser,
    ResourceNotFound,
    get_audit,
    get_current_user,
    get_storage,
)
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])

_ADMIN_TOKENS_SCOPE = "admin:tokens"


@router.delete(
    "/auth/tokens/{token_id}",
    operation_id="auth_revoke_token",
    status_code=204,
    response_class=Response,
)
async def auth_revoke_token(
    token_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> Response:
    row = await storage.get_personal_access_token(token_id)
    is_owner = row is not None and row.user_id == current_user.user_id
    is_admin = _ADMIN_TOKENS_SCOPE in current_user.effective_scopes
    # No existence oracle: a caller who is neither the owner nor an
    # admin:tokens holder cannot distinguish a foreign token from a missing
    # one — both are 404.
    if row is None or not (is_owner or is_admin):
        raise ResourceNotFound(f"personal_access_token:{token_id}")

    now = datetime.now(tz=UTC)
    # Idempotent at the storage layer — re-revoking keeps the first timestamp.
    await storage.revoke_personal_access_token(token_id=token_id, revoked_at=now)

    await audit.emit(
        event="eyenet.audit.auth.token.revoked",
        subject_kind="system_user",
        subject_id=row.user_id,
        system_user_id=current_user.user_id,
        payload={
            "token_id": str(token_id),
            "by_admin": is_admin and not is_owner,
        },
    )
    return Response(status_code=204)
