"""EYENET telemetry — tracing, logging, audit emit.

Tracing can be disabled at process start by setting either:

- ``EYENET_TRACING_DISABLED=1`` (EYENET-specific), or
- ``OTEL_SDK_DISABLED=true`` (OTel SDK standard).

When disabled, ``init_telemetry`` skips TracerProvider setup. OTel's default
``ProxyTracerProvider`` then returns ``NonRecordingSpan`` from every
``start_as_current_span``, so spans are no-ops. ``current_traceparent()``
returns ``None`` (the span context is invalid), and every
``_make_trace_context()`` site falls back to the zero traceparent — the
``BusEnvelopePublisher.publish`` invariant (``traceparent must be set``) is
still satisfied because the zero string is non-empty. structlog's
``_add_trace_ids`` processor checks ``span_ctx.is_valid`` before injecting
``trace_id``/``span_id``, so log lines simply omit those fields.

Logging is still configured even when tracing is off.
"""

from __future__ import annotations

import os

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased

from .audit import AuditEmitter
from .logging import configure_logging, get_logger
from .propagation import attach_from_headers, current_traceparent, extract, inject
from .sampling import should_keep_trace

_initialized: dict[tuple[str, str], TracerProvider] = {}

_DISABLED_ENV = "EYENET_TRACING_DISABLED"
_OTEL_DISABLED_ENV = "OTEL_SDK_DISABLED"
_TRUTHY = {"1", "true", "yes"}


def tracing_disabled() -> bool:
    """True iff EYENET_TRACING_DISABLED or OTEL_SDK_DISABLED is truthy in env."""

    return (
        os.environ.get(_DISABLED_ENV, "").strip().lower() in _TRUTHY
        or os.environ.get(_OTEL_DISABLED_ENV, "").strip().lower() in _TRUTHY
    )


def init_telemetry(
    *,
    service: str,
    instance_id: str,
    exporter: SpanExporter | None = None,
) -> TracerProvider | None:
    """Initialize OTel + structlog for a service. Idempotent per (service,
    instance_id) pair within a process.

    M1: span exporter defaults to ConsoleSpanExporter. Real OTLP gRPC export
    can be wired by the caller (passing `exporter=`); the env var
    `EYENET_OTLP_ENDPOINT` is read by `eyenet.cli.config`.

    Returns ``None`` when tracing is disabled via env var. Logging is still
    configured in that case.
    """

    if tracing_disabled():
        configure_logging(service=service, instance_id=instance_id)
        return None

    key = (service, instance_id)
    if key in _initialized:
        return _initialized[key]

    resource = Resource.create({"service.name": service, "service.instance.id": instance_id})
    # M9.6: head sampling is ParentBased(ALWAYS_ON) — keep every span the SDK sees
    # and honour an upstream sampling decision. The real cost control is tail-based
    # sampling at the OTel collector (API_PLAN §11.6; see operations/otel-collector.
    # sample.yaml), which alone can decide "keep the trace because it later emitted
    # attribution.linkage.proposed or errored". `should_keep_trace` is that
    # collector policy's Python source of truth.
    provider = TracerProvider(resource=resource, sampler=ParentBased(ALWAYS_ON))
    if exporter is not None:
        # Real exporter (e.g. OTLP): batch for throughput.
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        # ConsoleSpanExporter (dev/test): synchronous export, no background thread.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    otel_trace.set_tracer_provider(provider)

    configure_logging(service=service, instance_id=instance_id)

    _initialized[key] = provider
    return provider


__all__ = [
    "AuditEmitter",
    "attach_from_headers",
    "configure_logging",
    "current_traceparent",
    "extract",
    "get_logger",
    "init_telemetry",
    "inject",
    "should_keep_trace",
    "tracing_disabled",
]
