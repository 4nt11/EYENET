# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/cases/{case_id}/collaborators — add a case collaborator (admin:case).

Granting case access is sensitive (it is a clearance-adjacent capability), so it
requires ``admin:case`` rather than ``write:cases``.
"""

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
from eyenet.api.v1.cases._detail import audit_ctx, to_collaborator_summary
from eyenet.api.v1.schemas.cases import CaseCollaboratorAddRequest, CaseCollaboratorSummary
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/collaborators",
    operation_id="cases_add_collaborator",
    response_model=CaseCollaboratorSummary,
    status_code=200,
)
async def cases_add_collaborator(
    case_id: UUID,
    body: CaseCollaboratorAddRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:case"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseCollaboratorSummary:
    if await storage.get_case(case_id) is None:
        raise ResourceNotFound("case")
    try:
        row = await storage.add_case_collaborator(
            case_id=case_id,
            user_id=body.user_id,
            role=body.role_on_case,
            granted_by_user_id=current_user.user_id,
            **audit_ctx(audit),
        )
    except CaseError as exc:
        raise ConflictError(str(exc)) from exc
    return to_collaborator_summary(row)
