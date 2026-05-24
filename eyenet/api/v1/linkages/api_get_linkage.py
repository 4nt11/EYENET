"""GET /v1/linkages/{linkage_id} — linkage detail incl. evidence."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from eyenet.api.v1.schemas.linkages import LinkageDetail

router = APIRouter(tags=["linkages"])


@router.get(
    "/linkages/{linkage_id}",
    operation_id="linkages_get",
    response_model=LinkageDetail,
    status_code=200,
)
async def linkages_get(linkage_id: UUID) -> LinkageDetail:
    raise NotImplementedError("linkages_get (M9.0 skeleton)")
