"""EYENET metrics — OTel MeterProvider with dual exposition (API_PLAN §11.7).

Two surfaces, both opt-in by env var (§11.7.1):

- **Prometheus scrape** at ``/v1/metrics`` — gated by ``EYENET_API_METRICS_ENABLED``
  (truthy). The OTel ``PrometheusMetricReader`` registers a collector into
  ``prometheus_client``'s default registry; the endpoint serves
  ``generate_latest()`` (§11.7.1, scope ``read:metrics``).
- **OTLP push** — gated by ``EYENET_OTEL_ENDPOINT`` (an OTLP/gRPC endpoint).

Both readers share one MeterProvider, so every instrument is defined once and
feeds both surfaces.

**Cardinality discipline (§11.7.3, non-negotiable):** the Prometheus exposition
must never carry unbounded labels (per-user, per-request, per-target). We enforce
this two ways: (1) recording sites only ever pass the bounded attribute set each
instrument declares below, and (2) a per-instrument OTel ``View`` allow-list drops
any attribute key not in that set — defense in depth, so a fumbled recording site
cannot leak ``eyenet.user_id`` into Prometheus. Per-user analytics live on OTLP /
traces, never here.

Like ``init_telemetry``, instruments are created from the global meter at import
time; when metrics are disabled the global meter is the no-op proxy, so every
``.add()`` / ``.record()`` is a cheap no-op — recording sites never gate on
"metrics enabled".
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.resources import Resource
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from opentelemetry.metrics import CallbackOptions
    from opentelemetry.sdk.metrics.export import MetricReader

_METRICS_ENABLED_ENV = "EYENET_API_METRICS_ENABLED"
_OTEL_ENDPOINT_ENV = "EYENET_OTEL_ENDPOINT"
_TRUTHY = {"1", "true", "yes"}

_METER_NAME = "eyenet.api"
_initialized: dict[tuple[str, str], MeterProvider] = {}

# --- instrument catalog + their allowed (bounded) Prometheus label sets -------
# The value is the frozenset of attribute keys the instrument may carry in
# exposition. An empty set means "no labels". Anything a recording site passes
# outside this set is dropped by the View built in _cardinality_views().
_ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "eyenet_api_requests_total": frozenset({"method", "route", "status"}),
    "eyenet_api_request_duration_seconds": frozenset({"method", "route"}),
    "eyenet_api_sse_connections": frozenset({"stream"}),
    "eyenet_api_sse_events_delivered_total": frozenset({"stream"}),
    "eyenet_api_sse_events_dropped_total": frozenset({"stream", "topic", "reason"}),
    "eyenet_api_sse_terminated_total": frozenset({"stream", "reason"}),
    "eyenet_api_sse_delivery_lag_seconds": frozenset({"stream"}),
    "eyenet_api_auth_events_total": frozenset({"event", "outcome"}),
    "eyenet_api_scope_cache_hits_total": frozenset(),
    "eyenet_api_scope_cache_misses_total": frozenset(),
    "eyenet_api_audit_publish_failures_total": frozenset(),
    "eyenet_api_idempotency_replays_total": frozenset(),
    "eyenet_api_trace_propagation_missing_total": frozenset({"source"}),
    "eyenet_api_healthy": frozenset(),
    "eyenet_api_ready": frozenset({"component"}),
    "eyenet_api_storage_open": frozenset(),
    "eyenet_api_bus_connected": frozenset(),
    # self-reported host stats (§11.7.3 bounded labels; disk path ∈ {data,root})
    "eyenet_sys_cpu_percent": frozenset(),
    "eyenet_sys_mem_used_bytes": frozenset(),
    "eyenet_sys_mem_used_percent": frozenset(),
    "eyenet_sys_disk_used_bytes": frozenset({"path"}),
    "eyenet_sys_load1": frozenset(),
}


def metrics_enabled() -> bool:
    """True iff EYENET_API_METRICS_ENABLED is truthy — gates the /v1/metrics route."""
    return os.environ.get(_METRICS_ENABLED_ENV, "").strip().lower() in _TRUTHY


def _cardinality_views() -> list[View]:
    # One allow-list View per instrument (§11.7.3). attribute_keys is a keep-list,
    # so any key not named here is stripped before aggregation/exposition.
    return [
        View(instrument_name=name, attribute_keys=set(keys))
        for name, keys in _ALLOWED_ATTRS.items()
    ]


def init_metrics(
    *,
    service: str,
    instance_id: str,
    extra_readers: Iterable[MetricReader] | None = None,
) -> MeterProvider | None:
    """Set up the MeterProvider. Idempotent per (service, instance_id).

    Attaches a Prometheus reader when ``EYENET_API_METRICS_ENABLED`` is truthy and
    an OTLP periodic reader when ``EYENET_OTEL_ENDPOINT`` is set. ``extra_readers``
    is for tests (e.g. an in-memory reader). Returns ``None`` when no reader is
    configured (nothing to export → leave the global no-op provider in place).
    """
    readers: list[MetricReader] = list(extra_readers or [])

    if metrics_enabled():
        # Lazy: only pull the Prometheus reader when scrape is actually on.
        from opentelemetry.exporter.prometheus import PrometheusMetricReader  # noqa: PLC0415

        readers.append(PrometheusMetricReader())

    endpoint = os.environ.get(_OTEL_ENDPOINT_ENV, "").strip()
    if endpoint:
        # Lazy: avoid importing the heavy grpc stack unless OTLP push is configured.
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # noqa: PLC0415
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # noqa: PLC0415

        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint)))

    if not readers:
        return None

    key = (service, instance_id)
    if key in _initialized:
        return _initialized[key]

    resource = Resource.create({"service.name": service, "service.instance.id": instance_id})
    provider = MeterProvider(resource=resource, metric_readers=readers, views=_cardinality_views())
    otel_metrics.set_meter_provider(provider)
    _initialized[key] = provider
    return provider


def prometheus_exposition() -> tuple[bytes, str]:
    """Render the current metrics as Prometheus text exposition.

    Returns ``(body, content_type)``. The OTel ``PrometheusMetricReader`` feeds
    ``prometheus_client``'s default registry, so ``generate_latest()`` emits every
    EYENET instrument in ``text/plain; version=0.0.4``.
    """
    return generate_latest(), CONTENT_TYPE_LATEST


# --- the instrument catalog (§11.7.2) ---------------------------------------
# Created from the global meter; no-op proxies until init_metrics sets a provider.
_meter = otel_metrics.get_meter(_METER_NAME)

requests_total = _meter.create_counter(
    "eyenet_api_requests_total", description="HTTP requests by method/route/status."
)
request_duration_seconds = _meter.create_histogram(
    "eyenet_api_request_duration_seconds", unit="s", description="HTTP request latency."
)
sse_connections = _meter.create_up_down_counter(
    "eyenet_api_sse_connections", description="Open SSE connections by stream (gauge)."
)
sse_events_delivered_total = _meter.create_counter(
    "eyenet_api_sse_events_delivered_total", description="SSE events delivered."
)
sse_events_dropped_total = _meter.create_counter(
    "eyenet_api_sse_events_dropped_total", description="SSE events dropped (backpressure)."
)
sse_terminated_total = _meter.create_counter(
    "eyenet_api_sse_terminated_total", description="SSE connections terminated by reason."
)
sse_delivery_lag_seconds = _meter.create_histogram(
    "eyenet_api_sse_delivery_lag_seconds", unit="s", description="now - event ts at delivery."
)
auth_events_total = _meter.create_counter(
    "eyenet_api_auth_events_total", description="Auth events by event/outcome."
)
scope_cache_hits_total = _meter.create_counter(
    "eyenet_api_scope_cache_hits_total", description="Authorizer scope-cache hits."
)
scope_cache_misses_total = _meter.create_counter(
    "eyenet_api_scope_cache_misses_total", description="Authorizer scope-cache misses."
)
audit_publish_failures_total = _meter.create_counter(
    "eyenet_api_audit_publish_failures_total", description="Audit publish failures (alert > 0)."
)
idempotency_replays_total = _meter.create_counter(
    "eyenet_api_idempotency_replays_total", description="Idempotent write replays served."
)
trace_propagation_missing_total = _meter.create_counter(
    "eyenet_api_trace_propagation_missing_total",
    description="Envelopes/requests received with a missing/zero trace (SLI; alert > 0).",
)

# --- health gauges (observable; read a module-local state dict at scrape) -----
# The /healthz and /readyz handlers call set_health(...); the observable gauges'
# callbacks read the snapshot at collection time so a scrape never blocks on a
# live probe. Absent readiness components read 0 (not-ready) until first set.
_health: dict[str, float] = {}


def set_health(key: str, value: bool) -> None:
    """Record a health/readiness signal (e.g. "healthy", "ready:storage")."""
    _health[key] = 1.0 if value else 0.0


def _obs(key: str) -> Callable[[CallbackOptions], Iterable[Observation]]:
    def _cb(_options: CallbackOptions) -> Iterable[Observation]:
        return [Observation(_health.get(key, 0.0))]

    return _cb


def _obs_ready(_options: CallbackOptions) -> Iterable[Observation]:
    return [
        Observation(value, {"component": key.split(":", 1)[1]})
        for key, value in _health.items()
        if key.startswith("ready:")
    ]


_meter.create_observable_gauge("eyenet_api_healthy", callbacks=[_obs("healthy")])
_meter.create_observable_gauge("eyenet_api_ready", callbacks=[_obs_ready])
_meter.create_observable_gauge("eyenet_api_storage_open", callbacks=[_obs("storage_open")])
_meter.create_observable_gauge("eyenet_api_bus_connected", callbacks=[_obs("bus_connected")])


# --- self-reported host gauges (§11.7.3; psutil read at scrape time) ----------
# Same forensic data the authenticated /v1/system endpoint serves, exposed as
# metrics for Grafana. Disk needs the data volume, registered at API boot (dict
# avoids a `global`, mirroring the _health snapshot pattern above).
_sys_paths: dict[str, Path] = {}


def set_system_paths(data_dir: Path) -> None:
    """Register the data volume for the disk gauge (called at API boot)."""
    _sys_paths["data"] = data_dir


def _obs_cpu(_options: CallbackOptions) -> Iterable[Observation]:
    return [Observation(psutil.cpu_percent(interval=None))]


def _obs_mem_used(_options: CallbackOptions) -> Iterable[Observation]:
    return [Observation(float(psutil.virtual_memory().used))]


def _obs_mem_percent(_options: CallbackOptions) -> Iterable[Observation]:
    return [Observation(psutil.virtual_memory().percent)]


def _obs_load1(_options: CallbackOptions) -> Iterable[Observation]:
    return [Observation(os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0)]


def _obs_disk(_options: CallbackOptions) -> Iterable[Observation]:
    paths = {"root": Path("/"), **_sys_paths}
    out: list[Observation] = []
    for label, path in paths.items():
        try:
            used = shutil.disk_usage(path).used
        except OSError:
            continue
        out.append(Observation(float(used), {"path": label}))
    return out


_meter.create_observable_gauge("eyenet_sys_cpu_percent", callbacks=[_obs_cpu])
_meter.create_observable_gauge("eyenet_sys_mem_used_bytes", callbacks=[_obs_mem_used])
_meter.create_observable_gauge("eyenet_sys_mem_used_percent", callbacks=[_obs_mem_percent])
_meter.create_observable_gauge("eyenet_sys_disk_used_bytes", callbacks=[_obs_disk])
_meter.create_observable_gauge("eyenet_sys_load1", callbacks=[_obs_load1])


__all__ = [
    "audit_publish_failures_total",
    "auth_events_total",
    "idempotency_replays_total",
    "init_metrics",
    "metrics_enabled",
    "prometheus_exposition",
    "request_duration_seconds",
    "requests_total",
    "scope_cache_hits_total",
    "scope_cache_misses_total",
    "set_health",
    "set_system_paths",
    "sse_connections",
    "sse_delivery_lag_seconds",
    "sse_events_delivered_total",
    "sse_events_dropped_total",
    "sse_terminated_total",
    "trace_propagation_missing_total",
]
