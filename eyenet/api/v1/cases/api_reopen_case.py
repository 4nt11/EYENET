"""POST /v1/cases/{case_id}/reopen — closed → open, or archived → successor (§4.10.3)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseDetail, CaseReopenRequest

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/reopen",
    operation_id="cases_reopen",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_reopen(case_id: UUID, body: CaseReopenRequest) -> CaseDetail:
    raise NotImplementedError("cases_reopen (M9.0 skeleton)")
