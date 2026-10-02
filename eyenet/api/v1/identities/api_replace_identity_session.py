# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/identities/{identity_id}/session — rotate an identity's credential.

The "I logged out, here are fresh cookies" path: replace ONLY the encrypted
session blob (a forum cookies.txt, or a Telegram .session). Name, source, pacing,
evasion level, role — everything else is untouched. Re-provisioning is not needed
and would churn the config; this swaps the credential in place.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.contracts.source import SourceRow
from eyenet.identity_pool._provision import SessionValidationError, replace_identity_session
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])

_MAX_SESSION_BYTES = 1 * 1024 * 1024


@router.put(
    "/identities/{identity_id}/session",
    operation_id="identities_replace_session",
    response_model=IdentityDetail,
    status_code=200,
)
async def identities_replace_session(
    identity_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    data_dir: Annotated[Path, Depends(get_data_dir)],
    session_key: Annotated[object, Depends(get_session_key)],
    session: Annotated[
        UploadFile,
        File(description="the new credential file (forum cookies.txt or Telegram .session)"),
    ],
) -> IdentityDetail:
    if current_user.role != SystemUserRole.ADMIN:
        raise ScopeForbidden("admin (identity credential rotation is admin-only)")

    identity = await storage.get_identity(identity_id)
    if identity is None:
        raise ResourceNotFound("identity")
    source = await storage.get_source(identity.source_id)
    if not isinstance(source, SourceRow):
        raise ResourceNotFound("source")
    source_kind = SourceKind(source.kind)

    blob = await session.read()
    if len(blob) > _MAX_SESSION_BYTES:
        raise HTTPException(status_code=413, detail="session file too large")

    try:
        row = await replace_identity_session(
            storage=storage,
            session_key=session_key,  # type: ignore[arg-type]  # Fernet (deps returns object)
            data_dir=data_dir,
            identity_id=identity_id,
            source_kind=source_kind,
            secret_blob=blob,
        )
    except SessionValidationError as exc:
        raise RequestValidationError(
            [{"loc": ("body", "session"), "msg": str(exc), "type": "value_error"}]
        ) from exc

    await audit.emit(
        event="identity.session_replaced",
        subject_kind="identity",
        subject_id=row.id,
        system_user_id=current_user.user_id,
        payload={
            "name": row.name,
            "source_id": str(identity.source_id),
            "source_kind": source_kind.value,
            "session_sha256": hashlib.sha256(blob).hexdigest(),
        },
    )
    return IdentityDetail.from_domain(row)
