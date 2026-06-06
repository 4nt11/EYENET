# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/cases/{case_id}/seed-roots/{group_id} — promote one group to a seed root.

Idempotent: promoting an already-registered root is a no-op (no audit event).
Requires ``admin:case`` — anchoring the discovery tree is a sensitive operation.
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
from eyenet.api.v1.schemas.cases import CaseSeedRoots
from eyenet.storage.errors import CaseError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["cases"])


@router.post(
    "/cases/{case_id}/seed-roots/{group_id}",
    operation_id="cases_promote_seed_root",
    response_model=CaseSeedRoots,
    status_code=200,
)
async def cases_promote_seed_root(
    case_id: UUID,
    group_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:case"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CaseSeedRoots:
    existing = await storage.get_case(case_id)
    if existing is None:
        raise ResourceNotFound("case")
    roots = list(existing.seed_root_group_ids)
    if group_id not in roots:
        roots.append(group_id)
    try:
        updated = await storage.update_case_discovery_policy(
            case_id=case_id,
            seed_root_group_ids=roots,
            editor_user_id=current_user.user_id,
            **audit_ctx(audit),
        )
    except CaseError as exc:
        raise ConflictError(str(exc)) from exc
    return CaseSeedRoots(case_id=updated.id, seed_root_group_ids=updated.seed_root_group_ids)
