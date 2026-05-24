"""POST /v1/cases/{case_id}/collaborators — add a case collaborator."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseCollaboratorAddRequest, CaseCollaboratorSummary

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
) -> CaseCollaboratorSummary:
    raise NotImplementedError("cases_add_collaborator (M9.0 skeleton)")
