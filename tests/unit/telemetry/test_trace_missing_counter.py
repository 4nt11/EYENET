# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9.6 slice 4 — trace→REQUIRED cutover (count-only SLI).

The counter is spied via monkeypatch rather than observed through a MeterProvider:
the module instrument binds to the global (set-once) proxy, so spying on ``.add``
is the robust way to assert the increment.
"""

from __future__ import annotations

import pytest

from eyenet.telemetry.propagation import (
    ZERO_TRACEPARENT,
    attach_from_headers,
    is_zero_traceparent,
)

pytestmark = pytest.mark.unit

# A valid non-zero W3C traceparent (W3C spec example).
_VALID_TP = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


class _Spy:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict | None]] = []

    def add(self, amount: int, attributes: dict | None = None) -> None:
        self.calls.append((amount, attributes))


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    s = _Spy()
    monkeypatch.setattr("eyenet.telemetry.metrics.trace_propagation_missing_total", s)
    return s


def test_zero_traceparent_shape_and_helper() -> None:
    assert len(ZERO_TRACEPARENT) == 55
    assert is_zero_traceparent(None)
    assert is_zero_traceparent(ZERO_TRACEPARENT)
    assert not is_zero_traceparent(_VALID_TP)


def test_missing_trace_counts_when_tracing_on(spy: _Spy, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_TRACING_DISABLED", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    with attach_from_headers({}):  # no upstream trace
        pass
    assert spy.calls == [(1, {"source": "bus"})]


def test_zero_sentinel_counts(spy: _Spy, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_TRACING_DISABLED", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    with attach_from_headers({"traceparent": ZERO_TRACEPARENT}):
        pass
    assert spy.calls == [(1, {"source": "bus"})]


def test_valid_trace_does_not_count(spy: _Spy, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_TRACING_DISABLED", raising=False)
    with attach_from_headers({"traceparent": _VALID_TP}):
        pass
    assert spy.calls == []


def test_missing_trace_not_counted_when_tracing_off(
    spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EYENET_TRACING_DISABLED", "1")
    with attach_from_headers({}):
        pass
    assert spy.calls == []


def test_attach_never_raises_on_missing_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    # Count-only cutover: a missing trace must NEVER drop the event (no raise).
    monkeypatch.delenv("EYENET_TRACING_DISABLED", raising=False)
    entered = False
    with attach_from_headers({}):
        entered = True
    assert entered
