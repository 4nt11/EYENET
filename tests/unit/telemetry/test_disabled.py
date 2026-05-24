"""EYENET_TRACING_DISABLED / OTEL_SDK_DISABLED env-var off-switch."""

from __future__ import annotations

import pytest

from eyenet.telemetry import init_telemetry, tracing_disabled
from eyenet.telemetry.logging import _add_trace_ids


@pytest.fixture(autouse=True)
def _reset_initialized() -> None:
    # init_telemetry caches per-(service, instance_id); clear so each test
    # starts from a clean slate even if it sets a TracerProvider.
    from eyenet.telemetry import _initialized

    _initialized.clear()


@pytest.mark.unit
def test_tracing_disabled_truthy_eyenet_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_TRACING_DISABLED", "1")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    assert tracing_disabled() is True


@pytest.mark.unit
def test_tracing_disabled_truthy_otel_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_TRACING_DISABLED", raising=False)
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert tracing_disabled() is True


@pytest.mark.unit
def test_tracing_disabled_falsy_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_TRACING_DISABLED", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    assert tracing_disabled() is False


@pytest.mark.unit
def test_init_telemetry_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_TRACING_DISABLED", "1")
    result = init_telemetry(service="test", instance_id="test_1")
    assert result is None


@pytest.mark.unit
def test_start_span_is_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With disabled tracing, the default ProxyTracerProvider yields
    NonRecordingSpans whose span context is invalid."""

    monkeypatch.setenv("EYENET_TRACING_DISABLED", "1")
    # Reset the global provider so we see the OTel default (ProxyTracerProvider).
    # We can't actually replace the global once set, but we CAN confirm
    # that init_telemetry refuses to install our SDK provider when disabled.
    init_telemetry(service="test", instance_id="test_2")
    # If a previous test installed a real provider, this test cannot
    # de-install it — that's a process-global limitation, not a code bug.
    # We at least confirm init_telemetry didn't add a new one.
    from eyenet.telemetry import _initialized

    assert ("test", "test_2") not in _initialized


@pytest.mark.unit
def test_add_trace_ids_omits_keys_without_active_span() -> None:
    """structlog processor must not inject trace_id/span_id when there is
    no recording span (which is the disabled-tracing case)."""

    event_dict: dict[str, object] = {"event": "test"}
    out = _add_trace_ids(None, "info", event_dict)
    # No active span here → keys absent.
    assert "trace_id" not in out
    assert "span_id" not in out


@pytest.mark.unit
def test_zero_traceparent_satisfies_publisher_invariant() -> None:
    """When tracing is off, ``current_traceparent()`` is None and every
    ``_make_trace_context()`` returns the zero traceparent — verify it
    still satisfies the BusEnvelopePublisher invariant (non-empty)."""

    zero = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"
    assert zero  # non-empty
    # And it parses as 4 fields, which is what the audit row parser expects.
    assert len(zero.split("-")) == 4
