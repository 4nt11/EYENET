# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/candidates/{candidate_id} — full candidate detail (M9.D3).

Mentions + score breakdown + the (stubbed) per-collector eligibility block.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.candidates._detail import build_candidate_detail
from eyenet.api.v1.schemas.candidates import CandidateDetail
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["candidates"])


@router.get(
    "/candidates/{candidate_id}",
    operation_id="candidates_get",
    response_model=CandidateDetail,
    status_code=200,
)
async def candidates_get(
    candidate_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("read:candidates"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> CandidateDetail:
    detail = await build_candidate_detail(storage, candidate_id)
    if detail is None:
        raise ResourceNotFound("candidate")
    return detail
