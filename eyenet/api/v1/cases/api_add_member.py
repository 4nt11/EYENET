# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/cases/{case_id}/members — add a single subject to a case."""

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
from eyenet.api.v1.cases._detail import audit_ctx, to_member_summary
from eyenet.api.v1.schemas.cases import CaseMemberAddRequest, CaseMemberSummary
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/members",
    operation_id="cases_add_member",
    response_model=CaseMemberSummary,
    status_code=200,
)
async def cases_add_member(
    case_id: UUID,
    body: CaseMemberAddRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseMemberSummary:
    if await storage.get_case(case_id) is None:
        raise ResourceNotFound("case")
    try:
        row = await storage.add_case_member(
            case_id=case_id,
            subject_kind=body.subject_kind,
            subject_id=body.subject_id,
            added_by_user_id=current_user.user_id,
            reason=body.add_reason,
            **audit_ctx(audit),
        )
    except CaseError as exc:
        raise ConflictError(str(exc)) from exc
    return to_member_summary(row)
