"""GET /v1/cases — list cases visible to caller (§4.10.4 predicate)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from eyenet.api.v1.schemas.cases import CursorPageCaseSummary
from eyenet.api.v1.schemas.enums import CaseStatus

router = APIRouter(tags=["cases"])


@router.get(
    "/cases",
    operation_id="cases_list",
    response_model=CursorPageCaseSummary,
    status_code=200,
)
async def cases_list(
    cursor: str | None = None,
    limit: int = 50,
    include_total: int | None = None,
    status: CaseStatus | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> CursorPageCaseSummary:
    raise NotImplementedError("cases_list (M9.0 skeleton)")
