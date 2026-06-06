# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/cases/{case_id}/members/bulk — bulk add (≤500 subjects).

Best-effort sequential add: the first conflicting subject (duplicate / archived
case) raises 409 and earlier inserts are retained. The tier is recomputed once
the batch settles; ``audit_event_ids`` is empty in v1 (the storage layer emits
its own per-member audit rows; surfacing their ids is a follow-on).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.api.v1.cases._detail import audit_ctx
from eyenet.api.v1.schemas.cases import CaseMemberBulkAddRequest, CaseMemberBulkResult
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

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
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseMemberBulkResult:
    case = await storage.get_case(case_id)
    if case is None:
        raise ResourceNotFound("case")
    prior_tier = case.effective_tier
    ctx = audit_ctx(audit)
    affected: list[UUID] = []
    for subject in body.subjects:
        try:
            row = await storage.add_case_member(
                case_id=case_id,
                subject_kind=subject.subject_kind,
                subject_id=subject.subject_id,
                added_by_user_id=current_user.user_id,
                reason=body.add_reason,
                **ctx,
            )
        except CaseError as exc:
            raise ConflictError(
                f"bulk add failed at {subject.subject_kind.value}:{subject.subject_id}: {exc}"
            ) from exc
        affected.append(row.id)
    after = await storage.get_case(case_id)
    if after is None:  # pragma: no cover — existence checked above
        raise ResourceNotFound("case")
    return CaseMemberBulkResult(
        case_id=case_id,
        affected_member_ids=affected,
        audit_event_ids=[],
        effective_tier=after.effective_tier,
        prior_effective_tier=prior_tier,
    )
