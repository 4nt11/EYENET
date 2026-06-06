# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/cases/{case_id} — update title/description (open only, §4.10.3)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.api.v1.cases._detail import audit_ctx, build_case_detail
from eyenet.api.v1.schemas.cases import CaseDetail, CaseUpdateRequest
from eyenet.contracts.enums import CaseStatus
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.patch(
    "/cases/{case_id}",
    operation_id="cases_update",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_update(
    case_id: UUID,
    body: CaseUpdateRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseDetail:
    existing = await storage.get_case(case_id)
    if existing is None:
        raise ResourceNotFound("case")
    if existing.status is not CaseStatus.OPEN:
        raise ConflictError(f"cannot edit a case in status {existing.status.value}")
    try:
        await storage.update_case(
            case_id=case_id,
            title=body.title,
            description=body.description,
            editor_user_id=current_user.user_id,
            **audit_ctx(audit),
        )
    except CaseError as exc:
        raise ConflictError(str(exc)) from exc
    detail = await build_case_detail(storage, case_id)
    if detail is None:  # pragma: no cover — existence checked above
        raise ResourceNotFound("case")
    return detail
