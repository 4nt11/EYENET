"""POST /v1/cases/{case_id}/members/bulk — atomic bulk add (≤500 subjects)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseMemberBulkAddRequest, CaseMemberBulkResult

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/members/bulk",
    operation_id="cases_bulk_add_members",
    response_model=CaseMemberBulkResult,
    status_code=200,
)
async def cases_bulk_add_members(
    case_id: UUID,
    body: CaseMemberBulkAddRequest,
) -> CaseMemberBulkResult:
    raise NotImplementedError("cases_bulk_add_members (M9.0 skeleton)")
