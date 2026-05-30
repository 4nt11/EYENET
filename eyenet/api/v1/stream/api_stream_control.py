"""GET /v1/stream/control — SSE stream of eyenet.control.* events."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from eyenet.api.deps import StreamPrincipal, get_stream_principal

router = APIRouter(tags=["stream"])


@router.get(
    "/stream/control",
    operation_id="stream_control",
    response_class=StreamingResponse,
    status_code=200,
)
async def stream_control(
    principal: Annotated[StreamPrincipal, Depends(get_stream_principal)],
    token: str | None = Query(default=None, max_length=2048),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=128),
) -> StreamingResponse:
    # Auth runs first via the dependency; 401 on bad ?token= precedes this 501.
    raise NotImplementedError("stream_control (M9.0 skeleton)")
