# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/identities/{identity_id} — delete an unused identity.

Burn (POST .../burn) retires a COMPROMISED identity in place; delete REMOVES a
mistaken / never-wired one. Refuses with 409 when a collector still references
it (detach/remove that collector first) or it is actively claimed (IN_USE). An
unparseable id is a 404, never a 422 (no enumeration oracle — matches the other
identity routes). 204 on success.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_audit, get_storage
from eyenet.storage.errors import ResourceInUseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])


def _resolve_id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ResourceNotFound("identity") from exc


@router.delete("/identities/{identity_id}", operation_id="identities_delete", status_code=204)
async def identities_delete(
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    identity_id: str = Path(..., min_length=1, max_length=128),
) -> None:
    ident_uuid = _resolve_id(identity_id)
    if await storage.get_identity(ident_uuid) is None:
        raise ResourceNotFound("identity")
    try:
        await storage.delete_identity(identity_id=ident_uuid)
    except ResourceInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason": "identity_in_use", "references": exc.refs},
        ) from exc
    await audit.emit(
        event="eyenet.audit.identity.deleted",
        subject_kind="identity",
        subject_id=ident_uuid,
        system_user_id=current_user.user_id,
        payload={},
    )
