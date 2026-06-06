# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/cases/{case_id}/seed-roots — replace the seed-root set (M9.D4, §4.12).

Changing the set shifts the reachable-root dimension of the §4.12.3 eligibility
predicate; the recompute is implicit (the predicate reads the live set), so the
next ``GET /v1/candidates`` reflects the change. Emits ``case.seed_roots_changed``.
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
from eyenet.api.v1.schemas.cases import CaseSeedRoots, CaseSeedRootsReplaceRequest
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.put(
    "/cases/{case_id}/seed-roots",
    operation_id="cases_replace_seed_roots",
    response_model=CaseSeedRoots,
    status_code=200,
)
async def cases_replace_seed_roots(
    case_id: UUID,
    body: CaseSeedRootsReplaceRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseSeedRoots:
    if await storage.get_case(case_id) is None:
        raise ResourceNotFound("case")
    try:
        updated = await storage.update_case_discovery_policy(
            case_id=case_id,
            seed_root_group_ids=body.seed_root_group_ids,
            editor_user_id=current_user.user_id,
            **audit_ctx(audit),
        )
    except CaseError as exc:
        raise ConflictError(str(exc)) from exc
    return CaseSeedRoots(case_id=updated.id, seed_root_group_ids=updated.seed_root_group_ids)
