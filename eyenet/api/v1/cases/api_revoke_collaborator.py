"""DELETE /v1/cases/{case_id}/collaborators/{collaborator_id} — soft-revoke."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import (
    CaseCollaboratorRevokeRequest,
    CaseCollaboratorSummary,
)

router = APIRouter(tags=["cases"])


@router.delete(
    "/cases/{case_id}/collaborators/{collaborator_id}",
    operation_id="cases_revoke_collaborator",
    response_model=CaseCollaboratorSummary,
    status_code=200,
)
async def cases_revoke_collaborator(
    case_id: UUID,
    collaborator_id: UUID,
    body: CaseCollaboratorRevokeRequest,
) -> CaseCollaboratorSummary:
    raise NotImplementedError("cases_revoke_collaborator (M9.0 skeleton)")
