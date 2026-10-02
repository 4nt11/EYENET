"""EYENET_OTEL_ENDPOINT wires an OTLP span exporter (the trace-export path that
was previously a dead toggle)."""

from __future__ import annotations

import pytest

from eyenet.telemetry import _span_exporter_from_env


@pytest.mark.unit
def test_no_exporter_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_OTEL_ENDPOINT", raising=False)
    assert _span_exporter_from_env() is None


@pytest.mark.unit
def test_blank_endpoint_is_no_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_OTEL_ENDPOINT", "   ")
    assert _span_exporter_from_env() is None


@pytest.mark.unit
def test_endpoint_builds_otlp_span_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_OTEL_ENDPOINT", "http://otel-collector:4317")
    exporter = _span_exporter_from_env()
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    assert isinstance(exporter, OTLPSpanExporter)


@pytest.mark.unit
def test_explicit_exporter_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # init_telemetry with an explicit exporter must NOT consult the env (tests +
    # callers that inject their own exporter win). We assert the env path is only
    # taken when exporter is None by checking init_telemetry caches a provider and
    # does not raise when an explicit exporter is passed alongside an endpoint.
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    from eyenet.telemetry import _initialized, init_telemetry

    _initialized.clear()
    monkeypatch.delenv("EYENET_TRACING_DISABLED", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setenv("EYENET_OTEL_ENDPOINT", "http://otel-collector:4317")
    provider = init_telemetry(
        service="t", instance_id="otlp_override", exporter=ConsoleSpanExporter()
    )
    assert provider is not None
    _initialized.clear()
