"""W3C trace context propagation helpers.

Thin wrappers on OTel's TraceContextTextMapPropagator so service code never
touches the propagator API directly. Inputs/outputs are plain dict[str, str]
header maps — what NATS gives us and what `Bus.publish(headers=...)` takes.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from opentelemetry import context as otel_context, trace as otel_trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()


def extract(headers: dict[str, str]) -> otel_context.Context:
    """Extract a W3C trace context from headers."""

    return _PROPAGATOR.extract(headers)


def inject(headers: dict[str, str], ctx: otel_context.Context | None = None) -> None:
    """Inject the current (or given) span context into `headers`, in-place."""

    _PROPAGATOR.inject(headers, context=ctx)


def current_traceparent() -> str | None:
    """Return the current span's traceparent header value, or None."""

    span = otel_trace.get_current_span()
    span_ctx = span.get_span_context()
    if not span_ctx.is_valid:
        return None
    headers: dict[str, str] = {}
    inject(headers)
    return headers.get("traceparent")


@contextlib.contextmanager
def attach_from_headers(headers: dict[str, str]) -> Iterator[None]:
    """Extract W3C trace context from headers and attach for this block.

    Use at the top of every bus subscriber handler body so spans started
    inside parent to the publisher's span instead of starting a new root.
    Critical: this must be called *inside* an ``asyncio.create_task`` target,
    not before scheduling — ``create_task`` snapshots the current context at
    schedule time, which in the bus delivery callback is empty.

    Idempotent on empty/invalid headers: ``extract`` returns an empty context
    in that case and child spans simply start new traces (the pre-fix
    behaviour, restored only when there is genuinely no upstream context).
    """

    ctx = extract(headers)
    token = otel_context.attach(ctx)
    try:
        yield
    finally:
        otel_context.detach(token)


__all__ = ["attach_from_headers", "current_traceparent", "extract", "inject"]
