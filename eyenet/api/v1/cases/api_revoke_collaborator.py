# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/cases/{case_id}/collaborators/{collaborator_id} — soft-revoke (admin:case)."""

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
from eyenet.api.v1.schemas.cases import CaseCollaboratorRevokeRequest, CaseCollaboratorSummary
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.delete(
    "/cases/{case_id}/collaborators/{collaborator_id}",
    operation_id="cases_revoke_collaborator",
    response_model=CaseCollaboratorSummary,
    status_code=200,
)
async def cases_revoke_collaborator(
    case_id: UUID,  # noqa: ARG001 — FastAPI path param; collaborator_id is globally unique
    collaborator_id: UUID,
    body: CaseCollaboratorRevokeRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:case"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseCollaboratorSummary:
    try:
        row = await storage.revoke_case_collaborator(
            collaborator_id=collaborator_id,
            revoker_user_id=current_user.user_id,
            reason=body.revocation_reason,
            **audit_ctx(audit),
        )
    except CaseError as exc:
        if "not found" in str(exc):
            raise ResourceNotFound("collaborator") from exc
        raise ConflictError(str(exc)) from exc
    return to_collaborator_summary(row)
