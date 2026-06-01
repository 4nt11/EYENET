# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/candidates/{candidate_id}/approve — queued -> approved (M9.D3).

Validates the candidate exists, the ``assigned_collector_id`` exists, and the
state transition is legal. It does **NOT** gate on eligibility — that check is
the Group E stub (operator-trusted in v1; see eligibility.py). 202: the
supervisor executes the join off-path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import (
    ConflictError,
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    get_audit,
    get_storage,
)
from eyenet.api.v1.candidates._detail import build_candidate_detail
from eyenet.api.v1.schemas.candidates import ApproveCandidateRequest, CandidateDetail
from eyenet.contracts.enums import CandidateState
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["candidates"])


@router.post(
    "/candidates/{candidate_id}/approve",
    operation_id="candidates_approve",
    response_model=CandidateDetail,
    status_code=202,
)
async def candidates_approve(
    candidate_id: UUID,
    body: ApproveCandidateRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:candidates"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> CandidateDetail:
    if await storage.get_candidate(candidate_id) is None:
        raise ResourceNotFound("candidate")
    if await storage.get_collector(body.assigned_collector_id) is None:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "assigned_collector_id"),
                    "msg": "collector not found",
                    "type": "value_error",
                },
            ],
        )
    try:
        await storage.transition_candidate(
            candidate_id=candidate_id,
            to_state=CandidateState.APPROVED,
            reviewed_by=f"operator:{current_user.user_id}",
            reviewed_at=datetime.now(tz=UTC),
            assigned_collector_id=body.assigned_collector_id,
        )
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc

    await audit.emit(
        event="eyenet.audit.candidate.approved",
        subject_kind="candidate",
        subject_id=candidate_id,
        system_user_id=current_user.user_id,
        payload={"assigned_collector_id": str(body.assigned_collector_id)},
    )
    detail = await build_candidate_detail(storage, candidate_id)
    if detail is None:  # pragma: no cover — existence checked above
        raise ResourceNotFound("candidate")
    return detail
