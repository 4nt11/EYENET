"""GET /v1/cases/{case_id}/collaborators — list case collaborators."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CursorPageCaseCollaboratorSummary

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}/collaborators",
    operation_id="cases_list_collaborators",
    response_model=CursorPageCaseCollaboratorSummary,
    status_code=200,
)
async def cases_list_collaborators(
    case_id: UUID,
    cursor: str | None = None,
    limit: int = 50,
    active_only: int | None = None,
) -> CursorPageCaseCollaboratorSummary:
    raise NotImplementedError("cases_list_collaborators (M9.0 skeleton)")
