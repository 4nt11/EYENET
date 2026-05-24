"""GET /v1/stream/audit — SSE stream of eyenet.audit.* events."""

from __future__ import annotations

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["stream"])


@router.get(
    "/stream/audit",
    operation_id="stream_audit",
    response_class=StreamingResponse,
    status_code=200,
)
async def stream_audit(
    token: str | None = Query(default=None, max_length=2048),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=128),
) -> StreamingResponse:
    raise NotImplementedError("stream_audit (M9.0 skeleton)")
