"""GET /v1/stream/audit — SSE stream of eyenet.audit.* events."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from eyenet.api.deps import StreamPrincipal, get_stream_principal

router = APIRouter(tags=["stream"])


@router.get(
    "/stream/audit",
    operation_id="stream_audit",
    response_class=StreamingResponse,
    status_code=200,
)
async def stream_audit(
    principal: Annotated[StreamPrincipal, Depends(get_stream_principal)],
    token: str | None = Query(default=None, max_length=2048),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=128),
) -> StreamingResponse:
    # Auth runs first via the dependency; 401 on bad ?token= precedes this 501.
    raise NotImplementedError("stream_audit (M9.0 skeleton)")
