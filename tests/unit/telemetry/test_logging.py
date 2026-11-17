"""structlog emits valid JSON with PLAN §9.1 fields."""

from __future__ import annotations

import json
from typing import cast

import pytest
import structlog
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider

from eyenet.telemetry.logging import configure_logging


@pytest.fixture(autouse=True, scope="module")
def _provider() -> None:
    otel_trace.set_tracer_provider(TracerProvider())


def _render_event(event: dict[str, object]) -> str | dict[str, object]:
    """Walk the configured structlog processors up to the stdlib bridge, then
    render as JSON.

    ``configure_logging`` ends its structlog chain with
    ``structlog.stdlib.ProcessorFormatter.wrap_for_formatter`` so stdlib's
    handler owns the final rendering. That wrapper returns an ``(args,
    kwargs)`` tuple, not an event dict, so iterating the whole chain would
    hand a tuple to the next processor and crash. We stop before the bridge
    and apply JSONRenderer ourselves to verify the schema the application
    observes at log time.
    """
    chain = structlog.get_config()["processors"]
    out: object = event
    logger = structlog.get_logger()
    for proc in chain:
        if getattr(proc, "__name__", "") == "wrap_for_formatter":
            break  # the stdlib bridge; hand-off to the application formatter
        out = proc(logger, "info", out)
    rendered = structlog.processors.JSONRenderer()(logger, "info", out)  # type: ignore[arg-type]
    return rendered  # type: ignore[no-any-return]


@pytest.mark.unit
def test_log_line_is_valid_json_with_required_fields() -> None:
    configure_logging(service="engine", instance_id="eng_1")
    rendered = _render_event({"event": "service.start"})
    parsed = json.loads(rendered) if isinstance(rendered, str) else rendered
    assert parsed["event"] == "service.start"
    assert parsed["service"] == "engine"
    assert parsed["instance_id"] == "eng_1"
    assert "ts" in parsed


@pytest.mark.unit
def test_trace_ids_added_inside_span() -> None:
    configure_logging(service="engine", instance_id="eng_1")
    tracer = otel_trace.get_tracer("test")
    with tracer.start_as_current_span("op"):
        rendered = _render_event({"event": "x"})
    parsed = json.loads(rendered) if isinstance(rendered, str) else rendered
    assert "trace_id" in parsed
    assert "span_id" in parsed
    assert len(cast("str", parsed["trace_id"])) == 32
    assert len(cast("str", parsed["span_id"])) == 16
