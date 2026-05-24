"""POST /v1/cases/{case_id}/close — open → closed (§4.10.3)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseCloseRequest, CaseDetail

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/close",
    operation_id="cases_close",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_close(case_id: UUID, body: CaseCloseRequest) -> CaseDetail:
    raise NotImplementedError("cases_close (M9.0 skeleton)")
