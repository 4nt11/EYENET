# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/stealer/families/{slug}: remove a family.

Rejects deletes while any rule still references the family, since an
orphan reference would silently WARN at rule-catalog load time and
leave an inconsistent catalog on disk.
"""

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
from eyenet.stealer.families.rw import delete_family, read_family
from eyenet.stealer.rules.catalog import load_catalog
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["stealer"])


@router.delete(
    "/stealer/families/{slug}",
    operation_id="stealer_families_delete",
    status_code=204,
)
async def stealer_families_delete(
    slug: str,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:stealer"))],
    _storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> None:
    try:
        fam = read_family(slug)
    except FileNotFoundError as exc:
        raise ResourceNotFound("stealer_family") from exc
    referencing = [r["id"] for r in load_catalog() if r.get("family") == slug]
    if referencing:
        raise ConflictError(
            f"family {slug!r} still referenced by {len(referencing)} rule(s): "
            f"{', '.join(referencing[:5])}{'...' if len(referencing) > 5 else ''}"  # noqa: PLR2004
        )
    try:
        delete_family(slug)
    except FileNotFoundError as exc:
        raise ResourceNotFound("stealer_family") from exc
    await audit.emit(
        event="eyenet.audit.stealer_family.deleted",
        subject_kind="stealer_family",
        evidence_ref=slug,
        system_user_id=current_user.user_id,
        payload={"name": fam.get("name"), "status": fam.get("status")},
    )
