"""Shared fixtures for integration tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def span_exporter() -> Iterator[InMemorySpanExporter]:
    """In-memory OTel span exporter for trace-continuity assertions.

    ``otel_trace.set_tracer_provider`` only succeeds once per process — by
    the time integration tests run, some other test may have installed a
    TracerProvider. We attach our exporter to whichever provider is
    current; if it's still the default proxy, we install a fresh SDK
    provider first.
    """

    exporter = InMemorySpanExporter()
    provider = otel_trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        new_provider = TracerProvider()
        new_provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(new_provider)
    exporter.clear()
    yield exporter
    exporter.clear()
