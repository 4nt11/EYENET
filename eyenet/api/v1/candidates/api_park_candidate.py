# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/candidates/{candidate_id}/park — joined -> parked (M9.D3).

Operator-initiated leave. The park reason is audited (the candidate row has no
dedicated park-reason column; ``rejection_reason`` stays reject-only).
"""

from __future__ import annotations

from datetime import UTC, datetime
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
from eyenet.api.v1.candidates._detail import build_candidate_detail
from eyenet.api.v1.schemas.candidates import CandidateDetail, ParkCandidateRequest
from eyenet.contracts.enums import CandidateState
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["candidates"])


@router.post(
    "/candidates/{candidate_id}/park",
    operation_id="candidates_park",
    response_model=CandidateDetail,
    status_code=202,
)
async def candidates_park(
    candidate_id: UUID,
    body: ParkCandidateRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:candidates"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CandidateDetail:
    if await storage.get_candidate(candidate_id) is None:
        raise ResourceNotFound("candidate")
    try:
        await storage.transition_candidate(
            candidate_id=candidate_id,
            to_state=CandidateState.PARKED,
            reviewed_by=f"operator:{current_user.user_id}",
            reviewed_at=datetime.now(tz=UTC),
        )
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc

    await audit.emit(
        event="eyenet.audit.candidate.parked",
        subject_kind="candidate",
        subject_id=candidate_id,
        system_user_id=current_user.user_id,
        payload={"reason": body.reason},
    )
    detail = await build_candidate_detail(storage, candidate_id)
    if detail is None:  # pragma: no cover — existence checked above
        raise ResourceNotFound("candidate")
    return detail
