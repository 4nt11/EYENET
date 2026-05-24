"""GET /v1/cases/{case_id} — case detail (§4.10.4 visibility)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseDetail

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}",
    operation_id="cases_get",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_get(case_id: UUID) -> CaseDetail:
    raise NotImplementedError("cases_get (M9.0 skeleton)")
