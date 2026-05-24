"""W3C trace context round-trips through extract/inject."""

from __future__ import annotations

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider

from eyenet.telemetry.propagation import (
    attach_from_headers,
    current_traceparent,
    extract,
    inject,
)


@pytest.fixture(autouse=True, scope="module")
def _provider() -> None:
    otel_trace.set_tracer_provider(TracerProvider())


@pytest.mark.unit
def test_traceparent_round_trip() -> None:
    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"  # pragma: allowlist secret
    headers = {"traceparent": tp}
    ctx = extract(headers)
    out: dict[str, str] = {}
    inject(out, ctx)
    assert out["traceparent"].startswith(
        "00-0af7651916cd43dd8448eb211c80319c-"
    )  # pragma: allowlist secret


@pytest.mark.unit
def test_current_traceparent_inside_span() -> None:
    tracer = otel_trace.get_tracer("test")
    with tracer.start_as_current_span("op"):
        tp = current_traceparent()
        assert tp is not None
        assert tp.startswith("00-")


@pytest.mark.unit
def test_current_traceparent_outside_span_is_none() -> None:
    assert current_traceparent() is None


@pytest.mark.unit
def test_attach_from_headers_with_valid_traceparent_makes_it_current() -> None:
    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"  # pragma: allowlist secret
    headers = {"traceparent": tp}
    tracer = otel_trace.get_tracer("test")
    with attach_from_headers(headers):
        # current_traceparent reflects the attached context's trace_id
        out: dict[str, str] = {}
        inject(out)
        assert out["traceparent"].startswith(
            "00-0af7651916cd43dd8448eb211c80319c-"
        )  # pragma: allowlist secret
        # A span started inside the block inherits the same trace_id
        with tracer.start_as_current_span("child") as span:
            assert format(span.get_span_context().trace_id, "032x") == (
                "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret
            )


@pytest.mark.unit
def test_attach_from_headers_with_empty_headers_is_noop() -> None:
    tracer = otel_trace.get_tracer("test")
    # No upstream context: child span starts a fresh trace, no crash.
    with attach_from_headers({}), tracer.start_as_current_span("child") as span:
        assert span.get_span_context().is_valid


@pytest.mark.unit
def test_attach_from_headers_detaches_on_exit() -> None:
    tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"  # pragma: allowlist secret
    headers = {"traceparent": tp}
    assert current_traceparent() is None
    with attach_from_headers(headers):
        out: dict[str, str] = {}
        inject(out)
        assert "0af7651916cd43dd8448eb211c80319c" in out["traceparent"]  # pragma: allowlist secret
    # Context restored: no leaked traceparent.
    assert current_traceparent() is None
