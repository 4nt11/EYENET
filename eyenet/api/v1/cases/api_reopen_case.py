# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/cases/{case_id}/reopen — closed → open, or archived → successor (§4.10.3).

- ``closed → open``: caller must own the case OR hold ``admin:case``.
- ``archived → open``: caller must hold ``admin:case``; the server mints a
  successor case (``parent_case_id`` set) and the reopener becomes its OWNER.
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
    ScopeForbidden,
    get_audit,
    get_storage,
)
from eyenet.api.v1.cases._detail import (
    audit_ctx,
    build_case_detail,
    has_admin_case,
    require_owner_or_admin_case,
)
from eyenet.api.v1.schemas.cases import CaseDetail, CaseReopenRequest
from eyenet.contracts.enums import CaseRoleOnCase, CaseStatus
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/reopen",
    operation_id="cases_reopen",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_reopen(
    case_id: UUID,
    body: CaseReopenRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseDetail:
    existing = await storage.get_case(case_id)
    if existing is None:
        raise ResourceNotFound("case")
    ctx = audit_ctx(audit)

    if existing.status is CaseStatus.CLOSED:
        await require_owner_or_admin_case(storage, case_id, current_user)
        try:
            await storage.reopen_case(
                case_id=case_id,
                reopener_user_id=current_user.user_id,
                **ctx,
            )
        except CaseError as exc:
            raise ConflictError(str(exc)) from exc
        result_id = case_id
    elif existing.status is CaseStatus.ARCHIVED:
        if not has_admin_case(current_user):
            raise ScopeForbidden("admin:case")
        successor = await storage.reopen_archived_case(
            case_id=case_id,
            reopener_user_id=current_user.user_id,
            reason=body.reopen_reason,
            **ctx,
        )
        await storage.add_case_collaborator(
            case_id=successor.id,
            user_id=current_user.user_id,
            role=CaseRoleOnCase.OWNER,
            granted_by_user_id=current_user.user_id,
            **ctx,
        )
        result_id = successor.id
    else:
        raise ConflictError(f"cannot reopen a case in status {existing.status.value}")

    detail = await build_case_detail(storage, result_id)
    if detail is None:  # pragma: no cover — just-written row must exist
        raise ResourceNotFound("case")
    return detail
