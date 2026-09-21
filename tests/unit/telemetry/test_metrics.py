# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9.6 metrics foundation — instrument catalog, cardinality view, exposition.

The cardinality View is tested against a LOCAL MeterProvider (never
``set_meter_provider``): OTel's global provider is set-once-per-process and
module-level instruments resolve their proxy exactly once, so driving the global
across tests is fragile. The View logic is identical on a local provider, and the
global boot path is exercised by the slice-3 endpoint integration test.
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from eyenet.telemetry import metrics as m

pytestmark = pytest.mark.unit


def _points(reader: InMemoryMetricReader, name: str) -> list:
    data = reader.get_metrics_data()
    pts: list = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    pts.extend(metric.data.data_points)
    return pts


def test_metrics_enabled_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_API_METRICS_ENABLED", raising=False)
    assert m.metrics_enabled() is False
    monkeypatch.setenv("EYENET_API_METRICS_ENABLED", "1")
    assert m.metrics_enabled() is True
    monkeypatch.setenv("EYENET_API_METRICS_ENABLED", "nonsense")
    assert m.metrics_enabled() is False


def test_init_metrics_none_when_no_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_API_METRICS_ENABLED", raising=False)
    monkeypatch.delenv("EYENET_OTEL_ENDPOINT", raising=False)
    assert m.init_metrics(service="eyenet-api", instance_id="no-reader") is None


def test_counter_records_with_bounded_attrs() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=m._cardinality_views())
    counter = provider.get_meter("t").create_counter("eyenet_api_requests_total")
    counter.add(1, {"method": "GET", "route": "/v1/actors", "status": "200"})
    provider.force_flush()
    pts = _points(reader, "eyenet_api_requests_total")
    assert len(pts) == 1
    assert pts[0].value == 1
    assert dict(pts[0].attributes) == {"method": "GET", "route": "/v1/actors", "status": "200"}


def test_cardinality_view_strips_unbounded_attr() -> None:
    # A fumbled recording site passes user_id — the View allow-list must drop it.
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=m._cardinality_views())
    counter = provider.get_meter("t").create_counter("eyenet_api_requests_total")
    counter.add(1, {"method": "GET", "route": "/v1/actors", "status": "200", "user_id": "u-123"})
    provider.force_flush()
    attrs = dict(_points(reader, "eyenet_api_requests_total")[0].attributes)
    assert "user_id" not in attrs
    assert set(attrs) == {"method", "route", "status"}


def test_every_instrument_has_an_allowlist() -> None:
    # Guard: a new metric cannot ship without a bounded-label decision (§11.7.3).
    for name in m._ALLOWED_ATTRS:
        assert name.startswith("eyenet_api_")
    # The catalog covers every metric named in API_PLAN §11.7.2.
    expected = {
        "eyenet_api_requests_total",
        "eyenet_api_request_duration_seconds",
        "eyenet_api_sse_connections",
        "eyenet_api_sse_events_delivered_total",
        "eyenet_api_sse_events_dropped_total",
        "eyenet_api_sse_terminated_total",
        "eyenet_api_sse_delivery_lag_seconds",
        "eyenet_api_auth_events_total",
        "eyenet_api_audit_publish_failures_total",
        "eyenet_api_idempotency_replays_total",
        "eyenet_api_trace_propagation_missing_total",
        "eyenet_api_healthy",
        "eyenet_api_ready",
    }
    assert expected <= set(m._ALLOWED_ATTRS)


def test_prometheus_exposition_is_text() -> None:
    body, content_type = m.prometheus_exposition()
    assert content_type.startswith("text/plain")
    assert isinstance(body, bytes)
