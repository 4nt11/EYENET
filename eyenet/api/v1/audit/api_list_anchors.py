"""GET /v1/audit/anchors — external-witness anchor records (§5.9)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from eyenet.api.v1.schemas.anchors import CursorPageAnchor

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/anchors",
    operation_id="audit_list_anchors",
    response_model=CursorPageAnchor,
    status_code=200,
)
async def audit_list_anchors(
    cursor: str | None = Query(default=None, max_length=4096),
    limit: int = Query(default=50, ge=1, le=500),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
) -> CursorPageAnchor:
    raise NotImplementedError("audit_list_anchors (M9.0 skeleton)")
