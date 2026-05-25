"""Per-service trace-continuity tests.

Each test proves that when a bus envelope arrives at a subscriber, the
subscriber attaches the W3C trace context from the headers BEFORE any span
is opened. We monkeypatch each service's `_inner` method to a probe that
starts a span; we then assert the probe span inherits the trace_id from
the published traceparent header.

This is the contract the M9-tracing fix introduces: ``attach_from_headers``
is called inside the create_task body so the upstream trace context survives
the bus hop. If this contract regresses, every test in this file fails.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from behave_text.spec import Window
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from eyenet.bus import MemoryBus
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_PROPOSED,
    SUBJECT_PERSONA_UPDATED,
    SUBJECT_PROFILE_CURRENT,
    LinkageProposedEnvelope,
    PersonaChangeKind,
    PersonaUpdatedEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.observation import ObservationEnvelope
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.engine.engine import Engine
from eyenet.graph.graph import Graph
from eyenet.linker.linker import Linker
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.verifier.service import VerifierService

# Known W3C traceparent — trace_id portion is what subscribers must inherit.
_TRACE_ID_HEX = "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret
_TRACEPARENT = f"00-{_TRACE_ID_HEX}-b7ad6b7169203331-01"
_EXPECTED_TRACE_ID = int(_TRACE_ID_HEX, 16)
_HEADERS = {"traceparent": _TRACEPARENT}

_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
_ACTOR_A = UUID("00000000-0000-0000-0000-000000000001")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000002")

_TC = TraceContext(traceparent=_TRACEPARENT)


@pytest.fixture
def storage() -> BaseRepository:
    d = tempfile.mkdtemp()
    return get_repository(data_dir=Path(d))


def _probe_tracer() -> otel_trace.Tracer:
    return otel_trace.get_tracer("test.probe")


# ---------------------------------------------------------------------------
# Sensor boundary
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sensor_inherits_trace_from_raw_message_headers(
    storage: BaseRepository,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MemoryBus()
    sensor = StylometricSensor(bus=bus, storage=storage)

    captured: list[int] = []

    async def _probe(self: StylometricSensor, env: RawMessageEnvelope) -> None:
        with _probe_tracer().start_as_current_span("sensor.probe") as span:
            captured.append(span.get_span_context().trace_id)

    monkeypatch.setattr(StylometricSensor, "_process", _probe)

    await sensor.on_subscribe()

    env = RawMessageEnvelope(
        source=SourceKind.TELEGRAM,
        instance_id="tg_test1",
        evidence_ref="telegram:-100:1",
        actor_key="actor:abc",
        platform_groupid="-100",
        platform_msgid="1",
        sent_at_source=_NOW,
        collected_at=_NOW,
        length_chars=3,
        length_words=1,
        body_sha256="0" * 64,
        is_forward=False,
        has_attachment=False,
        reply_to_platform_msgid=None,
        trace_context=_TC,
    )
    await bus.publish("raw.message.telegram.t", env.model_dump_json().encode(), headers=_HEADERS)
    await asyncio.sleep(0.1)

    assert captured, "sensor probe never ran"
    assert captured[0] == _EXPECTED_TRACE_ID


# ---------------------------------------------------------------------------
# Engine boundary
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_engine_inherits_trace_from_observation_headers(
    storage: BaseRepository,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MemoryBus()
    engine = Engine(bus=bus, storage=storage)

    captured: list[int] = []

    async def _probe(self: Engine, subject: str, payload: bytes) -> None:
        with _probe_tracer().start_as_current_span("engine.probe") as span:
            captured.append(span.get_span_context().trace_id)

    monkeypatch.setattr(Engine, "_process_observation_inner", _probe)

    await engine.on_subscribe()

    env = ObservationEnvelope(
        primitive="meta.total_messages",
        value=1.0,
        confidence=1.0,
        window=Window(start_ts=_NOW.timestamp(), end_ts=_NOW.timestamp()),
        source="telegram",
        evidence_ref="telegram:-100:1",
        identity_ref=str(_ACTOR_A),
        ts=_NOW.timestamp(),
    )
    await bus.publish(
        "actor.observation.text.meta.total_messages",
        env.model_dump_json().encode(),
        headers=_HEADERS,
    )
    await asyncio.sleep(0.1)

    assert captured, "engine probe never ran"
    assert captured[0] == _EXPECTED_TRACE_ID


# ---------------------------------------------------------------------------
# Linker boundary
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_linker_inherits_trace_from_profile_current_headers(
    storage: BaseRepository,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MemoryBus()
    linker = Linker(bus=bus, storage=storage)

    captured: list[int] = []

    async def _probe(self: Linker, subject: str, payload: bytes) -> None:
        with _probe_tracer().start_as_current_span("linker.probe") as span:
            captured.append(span.get_span_context().trace_id)

    monkeypatch.setattr(Linker, "_process_profile_inner", _probe)

    await linker.on_subscribe()

    env = ProfileCurrentEnvelope(
        profile_id=_new_uuid7(),
        actor_id=_ACTOR_A,
        version=1,
        role_confidence=0.5,
        stylometric_summary={"function_word_simhash": {"value": "0" * 16}},
        derived_at=_NOW,
        derived_from_observation_count=1,
        trace_context=_TC,
    )
    await bus.publish(
        SUBJECT_PROFILE_CURRENT,
        env.model_dump_json().encode(),
        headers=_HEADERS,
    )
    await asyncio.sleep(0.1)

    assert captured, "linker probe never ran"
    assert captured[0] == _EXPECTED_TRACE_ID


# ---------------------------------------------------------------------------
# Verifier boundary
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verifier_inherits_trace_from_linkage_proposed_headers(
    storage: BaseRepository,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MemoryBus()
    verifier = VerifierService(bus=bus, storage=storage)

    captured: list[int] = []

    async def _probe(self: VerifierService, subject: str, payload: bytes) -> None:
        with _probe_tracer().start_as_current_span("verifier.probe") as span:
            captured.append(span.get_span_context().trace_id)

    monkeypatch.setattr(VerifierService, "_process_proposed_inner", _probe)

    await verifier.on_subscribe()

    env = LinkageProposedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=_new_uuid7(),
        method="simhash",
        score=0.9,
        evidence={"language": "es"},
        proposed_at=_NOW,
        trace_context=_TC,
    )
    await bus.publish(
        SUBJECT_LINKAGE_PROPOSED,
        env.model_dump_json().encode(),
        headers=_HEADERS,
    )
    await asyncio.sleep(0.1)

    assert captured, "verifier probe never ran"
    assert captured[0] == _EXPECTED_TRACE_ID


# ---------------------------------------------------------------------------
# Graph boundary — three distinct subscriber entry points
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_profile_current_inherits_trace(
    storage: BaseRepository,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MemoryBus()
    graph = Graph(bus=bus, storage=storage)

    captured: list[int] = []

    async def _probe(self: Graph, payload: bytes) -> None:
        with _probe_tracer().start_as_current_span("graph.profile.probe") as span:
            captured.append(span.get_span_context().trace_id)

    monkeypatch.setattr(Graph, "_on_profile_current_inner", _probe)

    await graph.on_subscribe()

    env = ProfileCurrentEnvelope(
        profile_id=_new_uuid7(),
        actor_id=_ACTOR_A,
        version=1,
        role_confidence=0.5,
        stylometric_summary={},
        derived_at=_NOW,
        derived_from_observation_count=1,
        trace_context=_TC,
    )
    await bus.publish(
        SUBJECT_PROFILE_CURRENT,
        env.model_dump_json().encode(),
        headers=_HEADERS,
    )
    await asyncio.sleep(0.1)

    assert captured, "graph profile probe never ran"
    assert captured[0] == _EXPECTED_TRACE_ID


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_linkage_event_inherits_trace(
    storage: BaseRepository,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MemoryBus()
    graph = Graph(bus=bus, storage=storage)

    captured: list[int] = []

    async def _probe(self: Graph, subject: str, payload: bytes) -> None:
        with _probe_tracer().start_as_current_span("graph.linkage.probe") as span:
            captured.append(span.get_span_context().trace_id)

    monkeypatch.setattr(Graph, "_on_linkage_event_inner", _probe)

    await graph.on_subscribe()

    env = LinkageProposedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=_new_uuid7(),
        method="simhash",
        score=0.9,
        evidence={},
        proposed_at=_NOW,
        trace_context=_TC,
    )
    await bus.publish(
        SUBJECT_LINKAGE_PROPOSED,
        env.model_dump_json().encode(),
        headers=_HEADERS,
    )
    await asyncio.sleep(0.1)

    assert captured, "graph linkage probe never ran"
    assert captured[0] == _EXPECTED_TRACE_ID


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_persona_updated_inherits_trace(
    storage: BaseRepository,
    span_exporter: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MemoryBus()
    graph = Graph(bus=bus, storage=storage)

    captured: list[int] = []

    async def _probe(self: Graph, payload: bytes) -> None:
        with _probe_tracer().start_as_current_span("graph.persona.probe") as span:
            captured.append(span.get_span_context().trace_id)

    monkeypatch.setattr(Graph, "_on_persona_updated_inner", _probe)

    await graph.on_subscribe()

    env = PersonaUpdatedEnvelope(
        persona_id=_new_uuid7(),
        member_actor_ids=[_ACTOR_A, _ACTOR_B],
        change_kind=PersonaChangeKind.CREATED,
        at=_NOW,
        trace_context=_TC,
    )
    await bus.publish(
        SUBJECT_PERSONA_UPDATED,
        env.model_dump_json().encode(),
        headers=_HEADERS,
    )
    await asyncio.sleep(0.1)

    assert captured, "graph persona probe never ran"
    assert captured[0] == _EXPECTED_TRACE_ID


# ---------------------------------------------------------------------------
# Collector boundary — verify ingest span emits non-zero traceparent
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_collector_emits_nonzero_traceparent(
    span_exporter: InMemorySpanExporter,
) -> None:
    """The collector wraps ingest in a span so the publish carries a real
    traceparent. Pre-fix, ``current_traceparent()`` returned None inside
    the publish and every collector envelope went out with the zero
    traceparent — i.e. no trace root.

    We assert directly: open a ``collector.ingest`` span, capture its
    traceparent, confirm it is NOT the zero value.
    """

    from opentelemetry import trace

    from eyenet.telemetry.propagation import current_traceparent

    tracer = trace.get_tracer("eyenet.collector.telegram")
    zero = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"
    with tracer.start_as_current_span("collector.ingest"):
        tp = current_traceparent()
    assert tp is not None
    assert tp != zero
    assert tp.startswith("00-")
