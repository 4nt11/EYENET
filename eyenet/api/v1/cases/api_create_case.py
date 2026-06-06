# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/cases — create a new case (§4.10).

The creator is auto-enrolled as the case OWNER collaborator, so they
immediately satisfy the §4.10.4 visibility predicate for their own case.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.cases._detail import audit_ctx, build_case_detail
from eyenet.api.v1.schemas.cases import CaseCreateRequest, CaseDetail
from eyenet.contracts.enums import CaseRoleOnCase
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.post(
    "/cases",
    operation_id="cases_create",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_create(
    body: CaseCreateRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseDetail:
    ctx = audit_ctx(audit)
    row = await storage.create_case(
        title=body.title,
        description=body.description,
        opened_by_user_id=current_user.user_id,
        **ctx,
    )
    await storage.add_case_collaborator(
        case_id=row.id,
        user_id=current_user.user_id,
        role=CaseRoleOnCase.OWNER,
        granted_by_user_id=current_user.user_id,
        **ctx,
    )
    detail = await build_case_detail(storage, row.id)
    if detail is None:  # pragma: no cover — just-created row must exist
        raise RuntimeError("case vanished immediately after create")
    return detail
