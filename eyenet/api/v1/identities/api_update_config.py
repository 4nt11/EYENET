# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/identities/{identity_id}/config — edit a collector's non-secret config (admin).

Validates + merges the editable source_config fields (the forum pacing/evasion/engine/
fingerprint knobs, telegram monitor groups) and persists. Does NOT restart the collector:
config is read at collector boot, so the panel surfaces a conscious "restart to apply"
choice and the operator restarts the bound collector themselves (stop -> start).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    ScopeForbidden,
    get_audit,
    get_storage,
)
from eyenet.api.v1.identities._config import apply_config_updates
from eyenet.api.v1.schemas.identities import IdentityConfigUpdate, IdentityDetail
from eyenet.contracts.enums import SourceKind, SystemUserRole
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])


@router.patch(
    "/identities/{identity_id}/config",
    operation_id="identities_update_config",
    response_model=IdentityDetail,
    status_code=200,
)
async def identities_update_config(
    identity_id: UUID,
    body: IdentityConfigUpdate,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> IdentityDetail:
    if current_user.role != SystemUserRole.ADMIN:
        raise ScopeForbidden("admin (identity config is admin-only)")
    row = await storage.get_identity(identity_id)
    if row is None:
        raise ResourceNotFound("identity")
    source = await storage.get_source(row.source_id)
    if not isinstance(source, SourceRow):
        raise ResourceNotFound("source")

    provided = body.model_dump(exclude_unset=True)
    # Cooldown + notes are identity COLUMNS (any source kind), not source_config. Pull
    # them out BEFORE the kind-specific merge so a cooldown-only edit never trips the
    # "config editing not supported for source X" guard (e.g. matrix).
    pacing = {k: provided.pop(k) for k in ("cooldown_seconds", "notes") if k in provided}
    updated = row
    if provided:
        merged = apply_config_updates(SourceKind(source.kind), row.source_config or {}, provided)
        updated = await storage.update_identity_source_config(
            identity_id=identity_id, source_config=merged
        )
    if pacing:
        updated = await storage.update_identity_pacing(identity_id=identity_id, **pacing)
    await audit.emit(
        event="eyenet.audit.identity.config_updated",
        subject_kind="identity",
        subject_id=identity_id,
        system_user_id=current_user.user_id,
        payload={"fields": sorted([*provided.keys(), *pacing.keys()])},
    )
    collector = await storage.get_collector_by_identity(identity_id)
    return IdentityDetail.from_domain(updated, collector)
