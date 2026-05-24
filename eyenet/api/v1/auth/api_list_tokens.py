"""GET /v1/auth/tokens — paginate caller's PATs."""

from __future__ import annotations

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.auth import CursorPagePATSummary

router = APIRouter(tags=["auth"])


@router.get(
    "/auth/tokens",
    operation_id="auth_list_tokens",
    response_model=CursorPagePATSummary,
    status_code=200,
)
async def auth_list_tokens(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    include_total: bool = Query(default=False),
) -> CursorPagePATSummary:
    raise NotImplementedError("auth_list_tokens (M9.0 skeleton)")
