"""W3C trace context propagation helpers.

Thin wrappers on OTel's TraceContextTextMapPropagator so service code never
touches the propagator API directly. Inputs/outputs are plain dict[str, str]
header maps — what NATS gives us and what `Bus.publish(headers=...)` takes.
"""

from __future__ import annotations

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


__all__ = ["current_traceparent", "extract", "inject"]
