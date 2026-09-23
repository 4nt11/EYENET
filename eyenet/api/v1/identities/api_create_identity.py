# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/identities — provision an identity from an uploaded session file.

Multipart upload of a credential (Telegram: a ``.session`` file) plus its
non-secret config. The secret is converted, Fernet-encrypted, and written to
disk mode 0600 by :func:`eyenet.identity_pool._provision.provision_identity`;
the plaintext never persists server-side and never crosses the read surface.

Gated on ``write:identity`` AND the admin role: creating a credential is the
single most dangerous identity write, so it is admin-only even though the
lifecycle actions (claim/freeze/burn) accept any ``write:identity`` holder.
Creation is synchronous (there is no async settle step), so this returns 201
with the ``IdentityDetail`` — unlike the 202 action writes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    ScopeForbidden,
    get_audit,
    get_data_dir,
    get_session_key,
    get_storage,
)
from eyenet.api.v1.schemas.identities import IdentityDetail
from eyenet.contracts.enums import IdentityRole, SourceKind, SystemUserRole
from eyenet.contracts.source import SourceRow
from eyenet.identity_pool._provision import SessionValidationError, provision_identity
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])

# A Telethon .session is a small SQLite file (tens of KB). Cap generously to
# reject a mistaken bulk upload without truncating a legitimate session.
_MAX_SESSION_BYTES = 1 * 1024 * 1024


@router.post(
    "/identities",
    operation_id="identities_create",
    response_model=IdentityDetail,
    status_code=201,
)
async def identities_create(
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    data_dir: Annotated[Path, Depends(get_data_dir)],
    session_key: Annotated[object, Depends(get_session_key)],
    session: Annotated[UploadFile, File(description="the credential file (Telegram .session)")],
    name: Annotated[str, Form(min_length=1, max_length=128)],
    source_id: Annotated[UUID, Form()],
    telegram_api_id: Annotated[int | None, Form()] = None,
    telegram_api_hash: Annotated[str | None, Form(max_length=256)] = None,
    monitor_groups: Annotated[str | None, Form(description="comma-separated")] = None,
    cooldown_seconds: Annotated[int, Form(ge=0)] = 21_600,
    proxy_uri: Annotated[str | None, Form(max_length=1024)] = None,
    role: Annotated[IdentityRole, Form()] = IdentityRole.MONITOR,
    notes: Annotated[str | None, Form(max_length=4096)] = None,
) -> IdentityDetail:
    if current_user.role != SystemUserRole.ADMIN:
        raise ScopeForbidden("admin (identity provisioning is admin-only)")

    source = await storage.get_source(source_id)
    if not isinstance(source, SourceRow):
        raise ResourceNotFound("source")
    source_kind = SourceKind(source.kind)

    blob = await session.read()
    if len(blob) > _MAX_SESSION_BYTES:
        raise HTTPException(status_code=413, detail="session file too large")

    source_config = _build_source_config(
        source_kind,
        telegram_api_id=telegram_api_id,
        telegram_api_hash=telegram_api_hash,
        monitor_groups=monitor_groups,
    )

    try:
        row = await provision_identity(
            storage=storage,
            session_key=session_key,  # type: ignore[arg-type]  # Fernet (deps returns object)
            data_dir=data_dir,
            name=name,
            source_id=source_id,
            source_kind=source_kind,
            secret_blob=blob,
            source_config=source_config,
            role=role,
            cooldown_seconds=cooldown_seconds,
            proxy_uri=proxy_uri,
            notes=notes,
        )
    except SessionValidationError as exc:
        raise RequestValidationError(
            [{"loc": ("body", "session"), "msg": str(exc), "type": "value_error"}]
        ) from exc

    await audit.emit(
        event="identity.provisioned",
        subject_kind="identity",
        subject_id=row.id,
        system_user_id=current_user.user_id,
        payload={
            "name": row.name,
            "source_id": str(source_id),
            "source_kind": source_kind.value,
            "session_sha256": hashlib.sha256(blob).hexdigest(),
        },
    )
    return IdentityDetail.from_domain(row)


def _build_source_config(
    source_kind: SourceKind,
    *,
    telegram_api_id: int | None,
    telegram_api_hash: str | None,
    monitor_groups: str | None,
) -> dict[str, object]:
    """Assemble the non-secret per-source config, keyed by IdentityFileEntry field
    names so the pool can splat it back into an entry. New sources add a branch."""
    if source_kind == SourceKind.TELEGRAM:
        if telegram_api_id is None or telegram_api_hash is None:
            raise RequestValidationError(
                [
                    {
                        "loc": ("body", "telegram_api_id"),
                        "msg": "telegram_api_id and telegram_api_hash are required for Telegram",
                        "type": "value_error",
                    }
                ]
            )
        groups = [g.strip() for g in (monitor_groups or "").split(",") if g.strip()]
        return {
            "telegram_api_id": telegram_api_id,
            "telegram_api_hash": telegram_api_hash,
            "monitor_groups": groups,
        }
    raise RequestValidationError(
        [
            {
                "loc": ("body", "source_id"),
                "msg": f"identity upload not supported for source: {source_kind.value}",
                "type": "value_error",
            }
        ]
    )
