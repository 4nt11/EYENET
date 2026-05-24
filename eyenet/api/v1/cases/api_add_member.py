"""POST /v1/cases/{case_id}/members — add a single subject to a case."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseMemberAddRequest, CaseMemberSummary

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/members",
    operation_id="cases_add_member",
    response_model=CaseMemberSummary,
    status_code=200,
)
async def cases_add_member(
    case_id: UUID,
    body: CaseMemberAddRequest,
) -> CaseMemberSummary:
    raise NotImplementedError("cases_add_member (M9.0 skeleton)")
