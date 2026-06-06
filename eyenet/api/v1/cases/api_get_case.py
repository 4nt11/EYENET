# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/cases/{case_id} — case detail (§4.10.4 visibility)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.cases._detail import build_case_detail, require_case_visible
from eyenet.api.v1.schemas.cases import CaseDetail
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["cases"])


@router.get(
    "/cases/{case_id}",
    operation_id="cases_get",
    response_model=CaseDetail,
    status_code=200,
)
async def cases_get(
    case_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:cases"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> CaseDetail:
    await require_case_visible(storage, case_id, current_user)
    detail = await build_case_detail(storage, case_id)
    if detail is None:  # pragma: no cover — visibility check already loaded it
        raise RuntimeError("case vanished after visibility check")
    return detail
