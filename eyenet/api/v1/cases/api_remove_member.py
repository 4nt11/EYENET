"""DELETE /v1/cases/{case_id}/members/{member_id} — soft-remove a single membership."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CaseMemberRemoveRequest, CaseMemberSummary

router = APIRouter(tags=["cases"])


@router.delete(
    "/cases/{case_id}/members/{member_id}",
    operation_id="cases_remove_member",
    response_model=CaseMemberSummary,
    status_code=200,
)
async def cases_remove_member(
    case_id: UUID,
    member_id: UUID,
    body: CaseMemberRemoveRequest,
) -> CaseMemberSummary:
    raise NotImplementedError("cases_remove_member (M9.0 skeleton)")
