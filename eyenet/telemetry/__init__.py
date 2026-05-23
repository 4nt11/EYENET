"""EYENET telemetry — tracing, logging, audit emit."""

from __future__ import annotations

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

from .audit import AuditEmitter
from .logging import configure_logging, get_logger
from .propagation import current_traceparent, extract, inject
from .sampling import should_keep_trace

_initialized: dict[tuple[str, str], TracerProvider] = {}


def init_telemetry(
    *,
    service: str,
    instance_id: str,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    """Initialize OTel + structlog for a service. Idempotent per (service,
    instance_id) pair within a process.

    M1: span exporter defaults to ConsoleSpanExporter. Real OTLP gRPC export
    can be wired by the caller (passing `exporter=`); the env var
    `EYENET_OTLP_ENDPOINT` is read by `eyenet.cli.config`.
    """

    key = (service, instance_id)
    if key in _initialized:
        return _initialized[key]

    resource = Resource.create({"service.name": service, "service.instance.id": instance_id})
    provider = TracerProvider(resource=resource)
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
    "configure_logging",
    "current_traceparent",
    "extract",
    "get_logger",
    "init_telemetry",
    "inject",
    "should_keep_trace",
]
