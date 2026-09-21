"""GET /v1/stream/all — SSE multiplex of every authorized topic."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from eyenet.api.deps import StreamPrincipal, get_bus, get_storage, get_stream_principal
from eyenet.api.streaming import make_sse_response, require_topic_set
from eyenet.api.streaming.sse import sse_events_ext
from eyenet.api.v1.schemas.enums import StreamTopic
from eyenet.contracts.bus import Bus
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["stream"])


@router.get(
    "/stream/all",
    operation_id="stream_all",
    response_class=StreamingResponse,
    status_code=200,
    openapi_extra=sse_events_ext([t.value for t in StreamTopic]),
)
async def stream_all(
    request: Request,
    principal: Annotated[StreamPrincipal, Depends(get_stream_principal)],
    bus: Annotated[Bus, Depends(get_bus)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    topic: Annotated[list[StreamTopic], Query()] = [],  # noqa: B006 — FastAPI needs a concrete default for a list query param
    token: str | None = Query(  # noqa: ARG001 — OpenAPI ?token= surface; read from the request by get_stream_principal
        default=None, max_length=2048
    ),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", max_length=128),
) -> StreamingResponse:
    # The ?topic= set must exactly equal the token's topics claim (§ 1603): any
    # drift — extra or missing — is a flat 401.
    topic_values = [t.value for t in topic]
    require_topic_set(principal, topic_values)
    return make_sse_response(
        request=request,
        bus=bus,
        storage=storage,
        principal=principal,
        topics=topic_values,
        last_event_id=last_event_id,
    )
