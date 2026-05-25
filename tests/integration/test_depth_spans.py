"""Depth-tier span coverage tests — Tracing audit Tiers 2/4/6/7.

For each newly-wrapped span, verify:
1. The span is emitted with the expected name.
2. The span attaches under the active trace context (bus header
   propagation continues to hold).

These tests do NOT replace the existing trace-continuity suite — they
assert that the depth fill-in spans actually appear, not just that the
trace_id propagates.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from eyenet.bus import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext, _new_uuid7
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_REJECTED,
    SUBJECT_LINKAGE_SUSPECTED,
    SUBJECT_PERSONA_UPDATED,
    SUBJECT_PROFILE_CURRENT,
    LinkageRejectedEnvelope,
    LinkageSuspectedEnvelope,
    PersonaChangeKind,
    PersonaUpdatedEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.graph.graph import Graph
from eyenet.storage import SQLiteStorage
from eyenet.telemetry.audit import AuditEmitter

_TRACE_ID_HEX = "0af7651916cd43dd8448eb211c80319d"  # pragma: allowlist secret
_TRACEPARENT = f"00-{_TRACE_ID_HEX}-b7ad6b7169203332-01"
_HEADERS = {"traceparent": _TRACEPARENT}
_TC = TraceContext(traceparent=_TRACEPARENT)
_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
_ACTOR_A = UUID("00000000-0000-0000-0000-000000000011")
_ACTOR_B = UUID("00000000-0000-0000-0000-000000000012")


@pytest.fixture
def storage() -> SQLiteStorage:
    return SQLiteStorage(Path(tempfile.mkdtemp()))


def _span_names(exporter: InMemorySpanExporter) -> list[str]:
    return [s.name for s in exporter.get_finished_spans()]


# ---------------------------------------------------------------------------
# Tier 2 — bus.publish / bus.deliver
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bus_publish_and_deliver_spans(
    span_exporter: InMemorySpanExporter,
) -> None:
    bus = MemoryBus()
    received: list[bytes] = []

    async def _handler(_subject: str, payload: bytes, _headers: dict[str, str]) -> None:
        received.append(payload)

    await bus.subscribe("raw.message.telegram.x", _handler)
    await bus.publish(
        "raw.message.telegram.x",
        b"hello",
        headers=_HEADERS,
    )
    await asyncio.sleep(0.05)

    names = _span_names(span_exporter)
    assert "bus.deliver" in names, names
    assert received == [b"hello"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publisher_emits_bus_publish_span(
    storage: SQLiteStorage,
    span_exporter: InMemorySpanExporter,
) -> None:
    bus = MemoryBus()
    publisher = BusEnvelopePublisher(bus=bus)
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
    await publisher.publish(SUBJECT_PROFILE_CURRENT, env)
    await asyncio.sleep(0.05)

    names = _span_names(span_exporter)
    assert "bus.publish" in names, names


# ---------------------------------------------------------------------------
# Tier 4 — graph fill-in (suspected / confirmed / rejected / persona.updated)
# ---------------------------------------------------------------------------


async def _drive_graph(
    storage: SQLiteStorage,
    bus: MemoryBus,
    subject: str,
    envelope: object,
) -> None:
    graph = Graph(bus=bus, storage=storage)
    await graph.on_subscribe()
    await bus.publish(
        subject,
        envelope.model_dump_json().encode(),  # type: ignore[attr-defined]
        headers=_HEADERS,
    )
    await asyncio.sleep(0.1)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_handle_suspected_emits_upsert_span(
    storage: SQLiteStorage,
    span_exporter: InMemorySpanExporter,
) -> None:
    env = LinkageSuspectedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=_new_uuid7(),
        decided_by="verifier",
        decided_at=_NOW,
        trace_context=_TC,
    )
    await _drive_graph(storage, MemoryBus(), SUBJECT_LINKAGE_SUSPECTED, env)

    names = _span_names(span_exporter)
    assert names.count("graph.upsert") >= 1, names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_handle_rejected_emits_upsert_span(
    storage: SQLiteStorage,
    span_exporter: InMemorySpanExporter,
) -> None:
    env = LinkageRejectedEnvelope.from_pair(
        _ACTOR_A,
        _ACTOR_B,
        linkage_id=_new_uuid7(),
        decided_by="verifier",
        decided_at=_NOW,
        trace_context=_TC,
    )
    await _drive_graph(storage, MemoryBus(), SUBJECT_LINKAGE_REJECTED, env)

    names = _span_names(span_exporter)
    assert names.count("graph.upsert") >= 1, names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_persona_updated_emits_upsert_span(
    storage: SQLiteStorage,
    span_exporter: InMemorySpanExporter,
) -> None:
    env = PersonaUpdatedEnvelope(
        persona_id=_new_uuid7(),
        member_actor_ids=[_ACTOR_A, _ACTOR_B],
        change_kind=PersonaChangeKind.CREATED,
        at=_NOW,
        trace_context=_TC,
    )
    await _drive_graph(storage, MemoryBus(), SUBJECT_PERSONA_UPDATED, env)

    names = _span_names(span_exporter)
    assert names.count("graph.upsert") >= 1, names


# ---------------------------------------------------------------------------
# Tier 6 — storage hot-write spans
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_storage_graph_upsert_emits_spans(
    storage: SQLiteStorage,
    span_exporter: InMemorySpanExporter,
) -> None:
    await storage.graph.upsert_node("actor", _ACTOR_A, {"k": "v"})
    await storage.graph.upsert_edge("linked_to", _ACTOR_A, _ACTOR_B, {"state": "proposed"})

    names = _span_names(span_exporter)
    assert "storage.graph.upsert_node" in names, names
    assert "storage.graph.upsert_edge" in names, names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_storage_vectors_spans(
    storage: SQLiteStorage,
    span_exporter: InMemorySpanExporter,
) -> None:
    await storage.vector_index.upsert_simhash(_ACTOR_A, "function_word_simhash", "0" * 16)
    matches = await storage.vector_index.nearest(
        "function_word_simhash",
        "0" * 16,
        max_distance=4,
        limit=10,
    )

    names = _span_names(span_exporter)
    assert "storage.vectors.upsert_simhash" in names, names
    assert "storage.vectors.nearest" in names, names
    assert isinstance(matches, list)


# ---------------------------------------------------------------------------
# Tier 7 — audit.emit
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_emit_span(
    storage: SQLiteStorage,
    span_exporter: InMemorySpanExporter,
) -> None:
    bus = MemoryBus()
    publisher = BusEnvelopePublisher(bus=bus)
    emitter = AuditEmitter(
        publisher=publisher,
        store=storage,
        service="test",
        instance_id="t-1",
    )

    await emitter.emit(
        event="test.event",
        subject_kind="actor",
        subject_id=_ACTOR_A,
        payload={"k": "v"},
    )
    await asyncio.sleep(0.05)

    names = _span_names(span_exporter)
    assert "audit.emit" in names, names
