"""PATCH /v1/cases/{case_id} — update title/description (open only)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseDetail, CaseUpdateRequest

router = APIRouter(tags=["cases"])


@router.patch(
    "/cases/{case_id}",
    operation_id="cases_update",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_update(case_id: UUID, body: CaseUpdateRequest) -> CaseDetail:
    raise NotImplementedError("cases_update (M9.0 skeleton)")
