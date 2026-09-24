# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/actor-groups/case — promote a crew to an investigation Case.

The operator-driven half of crew->case (the auto half runs in the batch sweep for
large, high-confidence crews). Idempotent on the crew's key: promoting the same
crew twice returns the existing case."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_storage
from eyenet.api.v1.cases._detail import audit_ctx
from eyenet.api.v1.schemas.actor_groups import OpenCrewCaseRequest, OpenCrewCaseResult
from eyenet.linker.crew_cases import crew_key_for, open_case_for_crew
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["actor-groups"])


@router.post(
    "/actor-groups/case",
    operation_id="actor_groups_open_case",
    response_model=OpenCrewCaseResult,
    status_code=200,
)
async def actor_groups_open_case(
    body: OpenCrewCaseRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> OpenCrewCaseResult:
    ctx = audit_ctx(audit)
    case = await open_case_for_crew(
        storage,
        members=body.members,
        top_infra=body.top_infra,
        opened_by_user_id=current_user.user_id,
        title=body.title,
        service=ctx["service"],
        instance_id=ctx["instance_id"],
    )
    return OpenCrewCaseResult(case_id=case.id, crew_key=crew_key_for(body.top_infra, body.members))
