# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/actor-groups/sweep-cases — auto-open Cases for big, confident crews.

The API form of ``eyenet crew-cases`` (so the frontend can trigger it). Opens a
Case for every crew with >= min_size members AND max edge score >= min_score,
skipping crews that already have one. The caller owns the opened cases."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.cases._detail import audit_ctx
from eyenet.api.v1.schemas.actor_groups import SweepCrewCasesRequest, SweepCrewCasesResult
from eyenet.linker.crew_cases import open_cases_for_big_crews
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["actor-groups"])


@router.post(
    "/actor-groups/sweep-cases",
    operation_id="actor_groups_sweep_cases",
    response_model=SweepCrewCasesResult,
    status_code=202,
)
async def actor_groups_sweep_cases(
    body: SweepCrewCasesRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> SweepCrewCasesResult:
    ctx = audit_ctx(audit)
    opened = await open_cases_for_big_crews(
        storage,
        opened_by_user_id=current_user.user_id,
        service=ctx["service"],
        instance_id=ctx["instance_id"],
        min_size=body.min_size,
        min_score=body.min_score,
    )
    return SweepCrewCasesResult(opened=opened)
