"""POST /v1/cases/{case_id}/members/bulk-remove — atomic bulk soft-remove (≤500 ids)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseMemberBulkRemoveRequest, CaseMemberBulkResult

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/members/bulk-remove",
    operation_id="cases_bulk_remove_members",
    response_model=CaseMemberBulkResult,
    status_code=200,
)
async def cases_bulk_remove_members(
    case_id: UUID,
    body: CaseMemberBulkRemoveRequest,
) -> CaseMemberBulkResult:
    raise NotImplementedError("cases_bulk_remove_members (M9.0 skeleton)")
