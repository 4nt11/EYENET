"""GET /v1/cases/{case_id}/members — list members of a case."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CursorPageCaseMemberSummary

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}/members",
    operation_id="cases_list_members",
    response_model=CursorPageCaseMemberSummary,
    status_code=200,
)
async def cases_list_members(
    case_id: UUID,
    cursor: str | None = None,
    limit: int = 50,
    active_only: int | None = None,
) -> CursorPageCaseMemberSummary:
    raise NotImplementedError("cases_list_members (M9.0 skeleton)")
