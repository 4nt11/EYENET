# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/stealer/families: create a new family, atomic write to disk."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    get_audit,
    get_storage,
)
from eyenet.api.v1.schemas.stealer_families import StealerFamilyIn, StealerFamilyOut
from eyenet.stealer.families.rw import write_family
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["stealer"])


@router.post(
    "/stealer/families",
    operation_id="stealer_families_create",
    response_model=StealerFamilyOut,
    status_code=201,
)
async def stealer_families_create(
    body: StealerFamilyIn,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:stealer"))],
    _storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerFamilyOut:
    payload = body.model_dump(exclude_none=True)
    try:
        stored = write_family(payload, allow_overwrite=False)
    except FileExistsError as exc:
        raise ConflictError(f"family {body.slug!r} already exists; use PUT to update") from exc
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    await audit.emit(
        event="eyenet.audit.stealer_family.created",
        subject_kind="stealer_family",
        subject_id=body.slug,
        system_user_id=current_user.user_id,
        payload={"name": body.name, "status": body.status},
    )
    return StealerFamilyOut.model_validate(stored)
