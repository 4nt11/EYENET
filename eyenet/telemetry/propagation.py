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

from eyenet.telemetry.metrics import trace_propagation_missing_total

_PROPAGATOR = TraceContextTextMapPropagator()

# Canonical all-zero W3C traceparent (valid 55-char shape, all-zero ids). Emitted
# by producers when there is no active span; the single source of truth so the
# ~9 former per-module copies can import instead of redefining.
ZERO_TRACEPARENT = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


def is_zero_traceparent(traceparent: str | None) -> bool:
    """True if ``traceparent`` is absent or the all-zero sentinel (no real trace)."""
    return traceparent is None or traceparent == ZERO_TRACEPARENT


def _count_trace_missing(source: str) -> None:
    # M9.6 §11.2 cutover, count-only (never drop): a received envelope/request with
    # no real upstream trace increments the SLI. Skipped when tracing is disabled
    # process-wide — every emit is a zero-sentinel then, so counting is pure noise
    # and the >0 alert would false-fire. Lazy import breaks the __init__ cycle
    # (tracing_disabled lives in the package __init__, which imports this module).
    from eyenet.telemetry import tracing_disabled  # noqa: PLC0415

    if tracing_disabled():
        return
    trace_propagation_missing_total.add(1, {"source": source})


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
    if not otel_trace.get_current_span(ctx).get_span_context().is_valid:
        # No valid upstream trace (absent headers or the zero sentinel) — count
        # the SLI, then proceed: child spans start a fresh trace as before.
        _count_trace_missing("bus")
    token = otel_context.attach(ctx)
    try:
        yield
    finally:
        otel_context.detach(token)


__all__ = [
    "ZERO_TRACEPARENT",
    "attach_from_headers",
    "current_traceparent",
    "extract",
    "inject",
    "is_zero_traceparent",
]
