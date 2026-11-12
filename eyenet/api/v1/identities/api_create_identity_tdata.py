# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/identities/tdata - provision a Telegram identity from a tdata archive.

The bulk-onboarding path for bought Telegram Desktop accounts: the operator
uploads the account's ``tdata`` folder as a zip/tar archive; we convert it
OFFLINE to a Telethon ``.session`` (opentele, reusing the tdata auth key - no
login from this host) and feed it into the SAME provisioning path as a
``.session`` upload. The ``api_id``/``api_hash`` the session is authorized under
are read from the tdata and stored with the identity, so the credential can't
drift from its session and trigger a re-auth ban; pass them on the form only to
override a non-default (custom-api) batch.

Archive handling is hardened against zip-slip, zip-bombs, and symlink escapes
(see ``eyenet.identity_pool._tdata``). Admin-only, like the ``.session`` create
path. OPSEC reminder: the account is only dialed later, through the identity's
proxy - never from this API host.
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
from eyenet.identity_pool._tdata import tdata_archive_to_session
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])

# Compressed archive cap at the edge (the extractor re-checks + caps the
# uncompressed stream). A fresh-account tdata is a few MB.
_MAX_TDATA_ARCHIVE_BYTES = 50 * 1024 * 1024


@router.post(
    "/identities/tdata",
    operation_id="identities_create_from_tdata",
    response_model=IdentityDetail,
    status_code=201,
)
async def identities_create_from_tdata(
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    data_dir: Annotated[Path, Depends(get_data_dir)],
    session_key: Annotated[object, Depends(get_session_key)],
    tdata: Annotated[
        UploadFile,
        File(description="Telegram Desktop tdata folder as a zip or tar(.gz/.bz2/.xz) archive"),
    ],
    name: Annotated[str, Form(min_length=1, max_length=128)],
    source_id: Annotated[UUID, Form()],
    telegram_api_id: Annotated[
        int | None, Form(description="override; default = the api the tdata is authorized under")
    ] = None,
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
    if source_kind != SourceKind.TELEGRAM:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "source_id"),
                    "msg": "tdata import is Telegram-only",
                    "type": "value_error",
                }
            ]
        )

    archive = await tdata.read()
    if len(archive) > _MAX_TDATA_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="tdata archive too large")

    # Extract (hardened) + convert OFFLINE to a .session blob. Operator-error
    # inputs (bad archive, no tdata, locked, no account) surface as 422.
    try:
        converted = await tdata_archive_to_session(archive)
    except SessionValidationError as exc:
        raise RequestValidationError(
            [{"loc": ("body", "tdata"), "msg": str(exc), "type": "value_error"}]
        ) from exc

    # Default the stored credentials to the ones the session is authorized under,
    # so the collector's first connect matches the auth key (no re-auth ban).
    api_id = telegram_api_id if telegram_api_id is not None else converted.api_id
    api_hash = telegram_api_hash or converted.api_hash
    groups = [g.strip() for g in (monitor_groups or "").split(",") if g.strip()]
    source_config: dict[str, object] = {
        "telegram_api_id": api_id,
        "telegram_api_hash": api_hash,
        "monitor_groups": groups,
    }

    # From here the converted .session blob flows through the identical path as a
    # .session upload (_materialize_secret -> encrypt 0600 -> create_identity).
    try:
        row = await provision_identity(
            storage=storage,
            session_key=session_key,  # type: ignore[arg-type]  # Fernet (deps returns object)
            data_dir=data_dir,
            name=name,
            source_id=source_id,
            source_kind=source_kind,
            secret_blob=converted.session_blob,
            source_config=source_config,
            role=role,
            cooldown_seconds=cooldown_seconds,
            proxy_uri=proxy_uri,
            notes=notes,
        )
    except SessionValidationError as exc:
        raise RequestValidationError(
            [{"loc": ("body", "tdata"), "msg": str(exc), "type": "value_error"}]
        ) from exc

    await audit.emit(
        event="identity.provisioned_from_tdata",
        subject_kind="identity",
        subject_id=row.id,
        system_user_id=current_user.user_id,
        payload={
            "name": row.name,
            "source_id": str(source_id),
            "source_kind": source_kind.value,
            "session_sha256": hashlib.sha256(converted.session_blob).hexdigest(),
            "telegram_api_id": api_id,
        },
    )
    return IdentityDetail.from_domain(row)
