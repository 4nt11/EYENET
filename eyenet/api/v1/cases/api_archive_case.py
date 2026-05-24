"""POST /v1/cases/{case_id}/archive — closed → archived, requires admin:case."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseArchiveRequest, CaseDetail

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/archive",
    operation_id="cases_archive",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_archive(case_id: UUID, body: CaseArchiveRequest) -> CaseDetail:
    raise NotImplementedError("cases_archive (M9.0 skeleton)")
