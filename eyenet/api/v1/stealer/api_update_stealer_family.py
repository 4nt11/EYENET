# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/stealer/families/{slug}: replace a family in place."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.api.v1.schemas.stealer_families import StealerFamilyIn, StealerFamilyOut
from eyenet.stealer.families.rw import read_family, write_family
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["stealer"])


@router.put(
    "/stealer/families/{slug}",
    operation_id="stealer_families_update",
    response_model=StealerFamilyOut,
)
async def stealer_families_update(
    slug: str,
    body: StealerFamilyIn,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:stealer"))],
    _storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerFamilyOut:
    if body.slug != slug:
        raise ConflictError(f"body.slug {body.slug!r} does not match URL slug {slug!r}")
    try:
        read_family(slug)
    except FileNotFoundError as exc:
        raise ResourceNotFound("stealer_family") from exc
    payload = body.model_dump(exclude_none=True, by_alias=True)
    try:
        stored = write_family(payload, allow_overwrite=True)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    await audit.emit(
        event="eyenet.audit.stealer_family.updated",
        subject_kind="stealer_family",
        system_user_id=current_user.user_id,
        payload={"slug": slug, "name": body.name, "status": body.status, "kind": body.kind},
    )
    return StealerFamilyOut.model_validate(stored)
