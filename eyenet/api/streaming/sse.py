# SPDX-License-Identifier: AGPL-3.0-or-later
"""SSE generator + delivery path (API_PLAN §3.5, §6.5 — M9 Group H).

One async generator drives every stream endpoint. Order of operations matters:
subscribe to the bus *first* (so live events queue during replay), then drain the
event-log replay for ``Last-Event-ID``, then live-tail. Overlap between the two is
deduped by the durable ``event_id`` (carried on the bus as the ``eyenet-event-id``
header by :meth:`BusEnvelopePublisher.publish`) — exact-once across the boundary.

Live events *without* a durable id (sister-service emissions such as
``attribution.linkage.proposed`` published over NATS, not via the operator-write
sequence) are delivered **without an SSE ``id:`` line**. Per the SSE spec a frame
with no id leaves the client's last-event-id unchanged, so a reconnect resumes
from the last *durable* event — those non-durable events are live-only/best-effort
(not in any event log, re-derivable via REST).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi.responses import StreamingResponse

from eyenet.api.deps import AuthError
from eyenet.api.streaming.otel import SseTracer
from eyenet.api.streaming.replay import StreamReplaySource
from eyenet.telemetry import metrics

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Collection

    from fastapi import Request

    from eyenet.api.deps import StreamPrincipal
    from eyenet.contracts.bus import Bus, Subscription
    from eyenet.contracts.event_log import EventLogRow
    from eyenet.storage.repository import BaseRepository

# `topics` throughout this module are ``StreamTopic`` *values* (bus-subject
# prefixes such as "attribution.linkage"). We deliberately do NOT import the
# ``StreamTopic`` enum here: it lives in ``eyenet.api.v1.schemas.enums``, whose
# package init (``eyenet.api.v1``) eagerly imports every route handler — the
# stream handlers among them import THIS module, so a runtime import would be a
# cold-start cycle. The v1 handlers pass ``topic.value`` at the boundary.

# --- config (operator-tunable; small-operator defaults) ---------------------
HEARTBEAT_SECONDS = float(os.environ.get("EYENET_SSE_HEARTBEAT_SECONDS", "15"))
HWM = int(os.environ.get("EYENET_SSE_HWM", "1000"))
SEGMENT_SECONDS = float(os.environ.get("EYENET_SSE_SEGMENT_SECONDS", "60"))
REPLAY_PAGE = int(os.environ.get("EYENET_SSE_REPLAY_PAGE", "512"))

# Topic value → bus subscribe patterns (§3.5). The control stream is a fan-in of
# the control plane plus two identity subjects the UI reacts to (banners, locks).
TOPIC_SUBJECTS: dict[str, tuple[str, ...]] = {
    "attribution.linkage": ("attribution.linkage.>",),
    "attribution.persona": ("attribution.persona.>",),
    "eyenet.audit": ("eyenet.audit.>",),
    "eyenet.control": (
        "eyenet.control.>",
        "eyenet.identity.freeze_all",
        "eyenet.identity.released",
    ),
}

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # tell nginx not to buffer the stream
}


# --- authorization ----------------------------------------------------------
def require_topic(principal: StreamPrincipal, topic: str) -> None:
    """401 (flat, no oracle) if the token was not minted for ``topic`` (a value)."""
    if topic not in principal.topics:
        raise AuthError("topic_not_in_token")


def require_topic_set(principal: StreamPrincipal, topics: Collection[str]) -> None:
    """`/stream/all`: request ``?topic=`` set must equal the token's claim (§ 1603)."""
    if set(topics) != set(principal.topics):
        raise AuthError("topic_set_mismatch")


_SENTINELS = ("stream.heartbeat", "stream.backpressure", "stream.expired", "stream.gap")


def sse_events_ext(topics: Collection[str]) -> dict[str, object]:
    """OpenAPI `x-eyenet-sse-events` (§9.7) — the honest wire contract for a stream.

    ``topics`` are ``StreamTopic`` values. Lists the bus subjects a stream may
    emit and the control sentinels. The typed per-event projection + TypeScript
    discriminated-union codegen it would feed are deferred with the frontend, so
    this describes what actually ships: the bus envelope JSON (replay frames add
    ``_replay: true`` metadata).
    """
    subjects: list[str] = []
    for t in topics:
        subjects.extend(TOPIC_SUBJECTS[t])
    return {
        "x-eyenet-sse-events": {
            "subjects": sorted(set(subjects)),
            "sentinels": list(_SENTINELS),
            "note": (
                "data: carries the bus envelope JSON; replay frames carry event-log "
                "metadata with _replay:true. Typed projection + TS codegen deferred "
                "to the frontend milestone."
            ),
        }
    }


# --- frame formatting -------------------------------------------------------
def _frame(
    *,
    event: str | None = None,
    data: str = "",
    event_id: str | None = None,
    comment: str | None = None,
) -> bytes:
    if comment is not None:
        return f": {comment}\n\n".encode()
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event is not None:
        lines.append(f"event: {event}")
    lines.extend(f"data: {dl}" for dl in data.split("\n"))
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _topic_of(subject: str) -> str:
    # "attribution.linkage.confirmed" → "attribution.linkage" (bounded label).
    return ".".join(subject.split(".")[:2])


def _event_name(subject: str) -> str:
    # "attribution.linkage.confirmed" → "linkage.confirmed"; "eyenet.identity.released"
    # → "identity.released". Drops the namespace segment.
    parts = subject.split(".")
    return ".".join(parts[1:]) if len(parts) > 1 else subject


def _replay_data(row: EventLogRow) -> str:
    # The event log stores no payload, only a digest (§11.5) — replay frames carry
    # metadata and the UI refetches full detail via REST.
    # ponytail: metadata-only replay; add a payload column to the event log only if
    # a consumer truly needs bodies without a follow-up GET.
    return json.dumps(
        {
            "event_id": str(row.event_id),
            "parent_id": str(row.parent_id),
            "subject": row.event_subject,
            "ts": row.ts.isoformat(),
            "actor": row.actor,
            "payload_digest": row.payload_digest,
            "_replay": True,
        }
    )


def _lag_ms(payload: bytes) -> float | None:
    try:
        emitted = json.loads(payload).get("emitted_at")
        if not isinstance(emitted, str):
            return None
        return (datetime.now(tz=UTC) - datetime.fromisoformat(emitted)).total_seconds() * 1000.0
    except (json.JSONDecodeError, ValueError):
        return None


def _expired(principal: StreamPrincipal) -> bool:
    return datetime.now(tz=UTC) >= principal.expires_at


# --- the generator ----------------------------------------------------------
async def sse_stream(
    *,
    request: Request,
    bus: Bus,
    storage: BaseRepository,
    principal: StreamPrincipal,
    topics: Collection[str],
    last_event_id: str | None,
) -> AsyncIterator[bytes]:
    """Replay-then-live-tail SSE body for the authorized ``topics`` (values)."""
    topic_set = set(topics)
    # "all" for the multiplex; otherwise the single topic's last segment
    # ("attribution.linkage" → "linkage") names the span/stream.
    stream_name = "all" if len(topic_set) > 1 else next(iter(topic_set)).rsplit(".", 1)[-1]
    connection_id = uuid4().hex

    queue: asyncio.Queue[tuple[str, bytes, dict[str, str]]] = asyncio.Queue(maxsize=HWM)
    overflow = asyncio.Event()

    async def _on_msg(subject: str, payload: bytes, headers: dict[str, str]) -> None:
        try:
            queue.put_nowait((subject, payload, headers))
        except asyncio.QueueFull:
            # ponytail: bounded per-connection queue; a slow consumer trips the
            # high-water mark and we drop the connection (client reconnects with
            # Last-Event-ID and replays the gap). Upgrade path: per-topic HWM
            # tuning if a real slow consumer shows up — unlikely at operator scale.
            metrics.sse_events_dropped_total.add(
                1, {"stream": stream_name, "topic": _topic_of(subject), "reason": "hwm"}
            )
            overflow.set()

    tracer = SseTracer(
        stream_name,
        user_id=principal.user_id,
        connection_id=connection_id,
        last_event_id=last_event_id,
        segment_seconds=SEGMENT_SECONDS,
    )
    subs: list[Subscription] = []
    seen: set[str] = set()
    close: dict[str, str] = {"reason": "shutdown"}
    try:
        for topic in topic_set:
            for pattern in TOPIC_SUBJECTS[topic]:
                subs.append(await bus.subscribe(pattern, _on_msg))
        tracer.accepted()
        if last_event_id is not None:
            async for frame in _replay_phase(storage, topic_set, last_event_id, seen, tracer):
                yield frame
        async for frame in _live_phase(request, queue, overflow, principal, seen, tracer, close):
            yield frame
    finally:
        for sub in subs:
            await sub.unsubscribe()
        tracer.close(close["reason"])


async def _replay_phase(
    storage: BaseRepository,
    topics: set[str],
    last_event_id: str,
    seen: set[str],
    tracer: SseTracer,
) -> AsyncIterator[bytes]:
    """Drain the durable event log after ``last_event_id`` (paged until short)."""
    cursor = _parse_cursor(last_event_id)
    source = StreamReplaySource(storage)
    while True:
        page = await source.replay(topics, cursor, REPLAY_PAGE)
        if not page:
            return
        for row in page:
            eid = str(row.event_id)
            seen.add(eid)
            frame = _frame(
                event=_event_name(row.event_subject), data=_replay_data(row), event_id=eid
            )
            lag = (datetime.now(tz=UTC) - row.ts).total_seconds() * 1000.0
            tracer.delivery(subject=row.event_subject, event_id=eid, lag_ms=lag, nbytes=len(frame))
            yield frame
        cursor = page[-1].event_id
        if len(page) < REPLAY_PAGE:
            return


async def _live_phase(
    request: Request,
    queue: asyncio.Queue[tuple[str, bytes, dict[str, str]]],
    overflow: asyncio.Event,
    principal: StreamPrincipal,
    seen: set[str],
    tracer: SseTracer,
    close: dict[str, str],
) -> AsyncIterator[bytes]:
    """Live-tail with heartbeat, token-expiry, and backpressure close.

    Records the close reason in ``close["reason"]`` for the connection-close span.
    """
    while True:
        if await request.is_disconnected():
            close["reason"] = "client_disconnect"
            return
        if _expired(principal):
            yield _frame(event="stream.expired", data=json.dumps({"reason": "token_expired"}))
            close["reason"] = "token_expired"
            return
        if overflow.is_set():
            yield _frame(event="stream.backpressure", data=json.dumps({"hwm": HWM}))
            yield _frame(event="stream.expired", data=json.dumps({"reason": "audit_backpressure"}))
            close["reason"] = "audit_backpressure"
            return
        try:
            subject, payload, headers = await asyncio.wait_for(
                queue.get(), timeout=HEARTBEAT_SECONDS
            )
        except TimeoutError:
            # Idle liveness is the SSE heartbeat comment (keeps proxies from reaping
            # the connection). The typed `stream.gap` sentinel is reserved for its
            # designed meaning — a reconnect cursor older than the oldest retained
            # event — which cannot arise while the pre-public build keeps every
            # event (no retention). ponytail: wire that path when retention lands.
            yield _frame(comment="heartbeat")
            continue
        eid = headers.get("eyenet-event-id")
        if eid is not None and eid in seen:
            continue  # already delivered from replay — exact-once boundary
        frame = _frame(event=_event_name(subject), data=payload.decode("utf-8"), event_id=eid)
        tracer.delivery(subject=subject, event_id=eid, lag_ms=_lag_ms(payload), nbytes=len(frame))
        yield frame


def _parse_cursor(last_event_id: str) -> UUID | None:
    # A malformed Last-Event-ID replays from the start rather than 400-ing a
    # reconnect — the client controls this header and a bad value is recoverable.
    try:
        return UUID(last_event_id)
    except ValueError:
        return None


def make_sse_response(
    *,
    request: Request,
    bus: Bus,
    storage: BaseRepository,
    principal: StreamPrincipal,
    topics: Collection[str],
    last_event_id: str | None,
) -> StreamingResponse:
    """Wrap :func:`sse_stream` as a ``text/event-stream`` response."""
    gen = sse_stream(
        request=request,
        bus=bus,
        storage=storage,
        principal=principal,
        topics=topics,
        last_event_id=last_event_id,
    )
    return StreamingResponse(gen, media_type="text/event-stream", headers=_SSE_HEADERS)


__all__ = [
    "HWM",
    "TOPIC_SUBJECTS",
    "make_sse_response",
    "require_topic",
    "require_topic_set",
    "sse_events_ext",
    "sse_stream",
]
