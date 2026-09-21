"""GET /v1/stream/control — SSE stream of eyenet.control.* + select identity events.

Surfaces panic, global freeze, and identity release so the UI can react in
realtime (banners, mode locks). Only `eyenet.identity.released` has a per-entity
event log, so that alone replays on reconnect; panic / freeze_all are live-only
(also durable in the audit chain, §3.5).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from eyenet.api.deps import StreamPrincipal, get_bus, get_storage, get_stream_principal
from eyenet.api.streaming import make_sse_response, require_topic
from eyenet.api.streaming.sse import sse_events_ext
from eyenet.api.v1.schemas.enums import StreamTopic
from eyenet.contracts.bus import Bus
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["stream"])

_TOPIC = StreamTopic.EYENET_CONTROL


@router.get(
    "/stream/control",
    operation_id="stream_control",
    response_class=StreamingResponse,
    status_code=200,
    openapi_extra=sse_events_ext([_TOPIC.value]),
)
async def stream_control(
    request: Request,
    principal: Annotated[StreamPrincipal, Depends(get_stream_principal)],
    bus: Annotated[Bus, Depends(get_bus)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    token: str | None = Query(  # noqa: ARG001 — OpenAPI ?token= surface; read from the request by get_stream_principal
        default=None, max_length=2048
    ),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=128),
) -> StreamingResponse:
    require_topic(principal, _TOPIC.value)
    return make_sse_response(
        request=request,
        bus=bus,
        storage=storage,
        principal=principal,
        topics=[_TOPIC.value],
        last_event_id=last_event_id,
    )
