# SPDX-License-Identifier: AGPL-3.0-or-later
"""DELETE /v1/cases/{case_id}/members/{member_id} — soft-remove a single membership."""

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
from eyenet.api.v1.cases._detail import audit_ctx, to_member_summary
from eyenet.api.v1.schemas.cases import CaseMemberRemoveRequest, CaseMemberSummary
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.delete(
    "/cases/{case_id}/members/{member_id}",
    operation_id="cases_remove_member",
    response_model=CaseMemberSummary,
    status_code=200,
)
async def cases_remove_member(
    case_id: UUID,  # noqa: ARG001 — FastAPI path param; member_id is globally unique
    member_id: UUID,
    body: CaseMemberRemoveRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseMemberSummary:
    try:
        row = await storage.remove_case_member(
            member_id=member_id,
            remover_user_id=current_user.user_id,
            reason=body.removal_reason,
            **audit_ctx(audit),
        )
    except CaseError as exc:
        if "not found" in str(exc):
            raise ResourceNotFound("member") from exc
        raise ConflictError(str(exc)) from exc
    return to_member_summary(row)
