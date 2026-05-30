# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/tokens — mint a new PAT for the caller (M9.A4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.exceptions import RequestValidationError

from eyenet.api.auth import mint_pat
from eyenet.api.deps import CurrentUser, get_audit, get_current_user, get_pat_pepper, get_storage
from eyenet.api.v1.schemas.auth import PATMinted, PATMintRequest
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/tokens",
    operation_id="auth_mint_token",
    response_model=PATMinted,
    status_code=201,
)
async def auth_mint_token(
    body: PATMintRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    pepper: Annotated[bytes, Depends(get_pat_pepper)],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
) -> PATMinted:
    # Scope ceiling (M9.A4 decision — "any held scope"): a PAT may carry any
    # scope the minter currently holds, and never more. The subset check also
    # rejects unknown/garbage scope strings. Escalation → 422.
    missing = sorted(set(body.scopes) - set(current_user.effective_scopes))
    if missing:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "scopes"),
                    "msg": f"cannot grant scopes you do not currently hold: {missing}",
                    "type": "value_error",
                },
            ],
        )

    now = datetime.now(tz=UTC)
    full_token, prefix, hash_hex = mint_pat(pepper)
    row = await storage.create_personal_access_token(
        user_id=current_user.user_id,
        name=body.name,
        prefix=prefix,
        hash_value=hash_hex,
        scopes=sorted(set(body.scopes)),
        created_at=now,
        expires_at=body.expires_at,
    )

    await audit.emit(
        event="eyenet.audit.auth.token.minted",
        subject_kind="system_user",
        subject_id=current_user.user_id,
        system_user_id=current_user.user_id,
        payload={
            "token_id": str(row.token_id),
            "name": row.name,
            "scopes": list(row.scopes),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            # Recorded for retry correlation. PAT mint is NOT replay-idempotent
            # (each call mints a distinct secret) — the key is forensic, not a
            # dedup guard. See development/PAT_RECIPES.md.
            "idempotency_key": idempotency_key,
        },
    )

    # `secret` is the full plaintext PAT — returned exactly ONCE, never re-read.
    return PATMinted(
        token_id=row.token_id,
        name=row.name,
        prefix=row.prefix,
        scopes=list(row.scopes),
        secret=full_token,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )
