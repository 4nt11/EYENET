"""POST /v1/cases — create a new case (§4.10)."""

from __future__ import annotations

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseCreateRequest, CaseDetail

router = APIRouter(tags=["cases"])


@router.post(
    "/cases",
    operation_id="cases_create",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_create(body: CaseCreateRequest) -> CaseDetail:
    raise NotImplementedError("cases_create (M9.0 skeleton)")
