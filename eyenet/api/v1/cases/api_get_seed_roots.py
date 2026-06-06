# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/cases/{case_id}/seed-roots — the discovery tree anchors (M9.D4, §4.12)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.cases._detail import require_case_visible
from eyenet.api.v1.schemas.cases import CaseSeedRoots
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}/seed-roots",
    operation_id="cases_get_seed_roots",
    response_model=CaseSeedRoots,
    status_code=200,
)
async def cases_get_seed_roots(
    case_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> CaseSeedRoots:
    row = await require_case_visible(storage, case_id, current_user)
    return CaseSeedRoots(case_id=row.id, seed_root_group_ids=row.seed_root_group_ids)
