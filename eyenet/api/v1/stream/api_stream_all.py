"""GET /v1/stream/all — SSE multiplex of every authorized topic."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from eyenet.api.deps import StreamPrincipal, get_stream_principal

router = APIRouter(tags=["stream"])


@router.get(
    "/stream/all",
    operation_id="stream_all",
    response_class=StreamingResponse,
    status_code=200,
)
async def stream_all(
    principal: Annotated[StreamPrincipal, Depends(get_stream_principal)],
    token: str | None = Query(default=None, max_length=2048),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=128),
) -> StreamingResponse:
    # Auth (the get_stream_principal dependency) runs first: an invalid/missing/
    # expired/wrong-type ?token= is 401 before this point. SSE delivery itself
    # (bus subscription + Last-Event-ID replay) lands with the streaming milestone.
    raise NotImplementedError("stream_all (M9.0 skeleton)")
