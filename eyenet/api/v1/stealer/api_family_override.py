# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator family-verdict override endpoints.

- PUT /v1/stealer/artifacts/{sha}/{folder}/family-override (write:stealer):
  upsert the override.
- DELETE /v1/stealer/artifacts/{sha}/{folder}/family-override
  (write:stealer): remove the override.

Overrides win over the classifier verdict at drawer read time and feed
the future tuning P/R dashboard (Phase 7 design doc).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.schemas.stealer import StealerFamilyOverrideIn, StealerFamilyOverrideOut
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["stealer"])


@router.put(
    "/stealer/artifacts/{archive_sha256}/{victim_folder:path}/family-override",
    operation_id="stealer_family_override_upsert",
    response_model=StealerFamilyOverrideOut,
    status_code=200,
)
async def stealer_family_override_upsert(
    body: StealerFamilyOverrideIn,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:stealer"))],
    archive_sha256: Annotated[str, Path(min_length=64, max_length=64)],
    victim_folder: Annotated[str, Path(min_length=1, max_length=512)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerFamilyOverrideOut:
    row = await storage.upsert_stealer_family_override(
        archive_sha256=archive_sha256,
        victim_folder=victim_folder,
        slug=body.slug,
        reason=body.reason,
        author_user_id=current_user.user_id,
    )
    await audit.emit(
        event="eyenet.audit.stealer_family_override.upsert",
        subject_kind="stealer_family_override",
        system_user_id=current_user.user_id,
        payload={
            "archive_sha256": archive_sha256,
            "victim_folder": victim_folder,
            "slug": body.slug,
            "reason": body.reason or "",
        },
    )
    return StealerFamilyOverrideOut.model_validate(row.model_dump())


@router.delete(
    "/stealer/artifacts/{archive_sha256}/{victim_folder:path}/family-override",
    operation_id="stealer_family_override_delete",
    status_code=204,
    response_class=Response,
)
async def stealer_family_override_delete(
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:stealer"))],
    archive_sha256: Annotated[str, Path(min_length=64, max_length=64)],
    victim_folder: Annotated[str, Path(min_length=1, max_length=512)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> Response:
    _removed = await storage.delete_stealer_family_override(archive_sha256, victim_folder)
    await audit.emit(
        event="eyenet.audit.stealer_family_override.delete",
        subject_kind="stealer_family_override",
        system_user_id=current_user.user_id,
        payload={"archive_sha256": archive_sha256, "victim_folder": victim_folder},
    )
    return Response(status_code=204)
