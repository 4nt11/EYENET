# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/cases/{case_id}/archive — closed → archived, requires admin:case."""

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
from eyenet.api.v1.schemas.cases import CaseArchiveRequest, CaseDetail
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/archive",
    operation_id="cases_archive",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_archive(
    case_id: UUID,
    body: CaseArchiveRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:case"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseDetail:
    if await storage.get_case(case_id) is None:
        raise ResourceNotFound("case")
    try:
        await storage.archive_case(
            case_id=case_id,
            archiver_user_id=current_user.user_id,
            reason=body.archive_reason,
            **audit_ctx(audit),
        )
    except CaseError as exc:
        raise ConflictError(str(exc)) from exc
    detail = await build_case_detail(storage, case_id)
    if detail is None:  # pragma: no cover — existence checked above
        raise ResourceNotFound("case")
    return detail
