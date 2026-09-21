# SPDX-License-Identifier: AGPL-3.0-or-later
"""Custom SSE span model (API_PLAN §11.4.1).

The spec calls for *disabling* the stock ``opentelemetry-instrumentation-fastapi``
SSE span (which ends on first response byte, orphaning every delivered event).
This codebase installs **no** ``FastAPIInstrumentor`` — every span is hand-rolled —
so there is nothing to suppress. If a future build adds it, exclude the stream
routes with ``OTEL_PYTHON_EXCLUDED_URLS=…,v1/stream`` so the request span does not
swallow the connection.

What this adds is the §11.4.1 tree so "show me everything that touched this
linkage" reaches the UI delivery at the bottom of the Collector's trace, with no
span outliving a minute:

    request → accept → segment(≤60s) → delivery(per event)   + close

Accept continues the request's trace context; segments are children of accept and
rotate every ``segment_seconds``; each delivery is a child of the current segment
and links back to accept. When telemetry is disabled (the default in tests) the
tracer hands back non-recording spans and every call here is a cheap no-op.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Link

from eyenet.telemetry import metrics

if TYPE_CHECKING:
    from opentelemetry.trace import Span

_tracer = trace.get_tracer("eyenet.api.sse")


class SseTracer:
    """Drives the §11.4.1 span lifecycle for one SSE connection."""

    def __init__(
        self,
        stream: str,
        *,
        user_id: UUID,
        connection_id: str,
        last_event_id: str | None,
        segment_seconds: float,
    ) -> None:
        self._stream = stream
        self._conn_id = connection_id
        self._segment_seconds = segment_seconds
        self._events = 0
        self._bytes = 0
        self._started = time.monotonic()
        self._accept: Span = _tracer.start_span(
            f"api.sse.accept.{stream}",
            attributes={
                "eyenet.user_id": str(user_id),
                "eyenet.stream": stream,
                "eyenet.connection_id": connection_id,
                "eyenet.last_event_id": last_event_id or "",
            },
        )
        self._accept_ctx = trace.set_span_in_context(self._accept)
        self._segment: Span | None = None
        self._segment_started = 0.0

    def accepted(self) -> None:
        """Close the short accept span — connection established, replay seeked."""
        self._accept.end()
        metrics.sse_connections.add(1, {"stream": self._stream})

    def _ensure_segment(self) -> None:
        now = time.monotonic()
        if self._segment is None or now - self._segment_started >= self._segment_seconds:
            if self._segment is not None:
                self._segment.end()
            self._segment = _tracer.start_span(
                f"api.sse.segment.{self._stream}",
                context=self._accept_ctx,
                attributes={"eyenet.connection_id": self._conn_id},
            )
            self._segment_started = now

    def delivery(
        self, *, subject: str, event_id: str | None, lag_ms: float | None, nbytes: int
    ) -> None:
        self._ensure_segment()
        ctx = trace.set_span_in_context(self._segment) if self._segment else self._accept_ctx
        span = _tracer.start_span(
            "api.sse.delivery",
            context=ctx,
            links=[Link(self._accept.get_span_context())],
            attributes={
                "eyenet.subject": subject,
                "eyenet.event_id": event_id or "",
                "eyenet.connection_id": self._conn_id,
                "eyenet.delivery_lag_ms": lag_ms if lag_ms is not None else -1.0,
            },
        )
        span.end()
        self._events += 1
        self._bytes += nbytes
        metrics.sse_events_delivered_total.add(1, {"stream": self._stream})
        if lag_ms is not None:
            metrics.sse_delivery_lag_seconds.record(lag_ms / 1000.0, {"stream": self._stream})

    def close(self, reason: str) -> None:
        metrics.sse_connections.add(-1, {"stream": self._stream})
        metrics.sse_terminated_total.add(1, {"stream": self._stream, "reason": reason})
        if self._segment is not None:
            self._segment.end()
        span = _tracer.start_span(
            f"api.sse.close.{self._stream}",
            context=self._accept_ctx,
            attributes={
                "eyenet.close_reason": reason,
                "total_events": self._events,
                "total_bytes": self._bytes,
                "connection_duration_ms": (time.monotonic() - self._started) * 1000.0,
            },
        )
        span.end()


__all__ = ["SseTracer"]
