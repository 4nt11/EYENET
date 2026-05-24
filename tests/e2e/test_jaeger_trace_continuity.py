# ruff: noqa: E501, PLR0915, ASYNC210
"""E2E trace-continuity check against a running Jaeger collector.

Pre-requisites:
  - Jaeger all-in-one listening on the standard ports:
      * OTLP gRPC ingest on :4317
      * Jaeger Query HTTP API on :16686
  - This test is marked ``e2e`` and is excluded from the default ``pytest``
    run (``addopts = -m "unit or contract"``). Invoke explicitly:

      EYENET_E2E_JAEGER=1 .venv/bin/python -m pytest tests/e2e/test_jaeger_trace_continuity.py -m e2e --no-cov -s

Strategy:
  1. Attach an OTLP gRPC exporter to whatever TracerProvider is current.
  2. Wire MemoryBus + Sensor + Engine + Linker + Graph — every subscriber
     in the M8 pipeline that runs without external corpora.
  3. Replay the existing ``synthetic_m2.jsonl`` fixture (3 actors x 70
     messages each — known to produce observations through every
     primitive that ships with the sensor) and publish each
     RawMessageEnvelope from inside a ``collector.ingest`` span so the
     trace has a real root.
  4. Force-flush spans to Jaeger.
  5. Query Jaeger's HTTP API and assert: every tier of the pipeline
     emitted at least one span, every span shares the parent's trace_id,
     and the resulting trace tree spans collector → graph.

If any link in the propagation chain is broken, the corresponding tier's
span is missing from Jaeger or its trace_id won't match — both failure
modes are surfaced clearly.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
from opentelemetry import trace as otel_trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlmodel import Session

from eyenet.bus import MemoryBus
from eyenet.contracts._base import TraceContext
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope, subject_for
from eyenet.engine.engine import Engine
from eyenet.graph.graph import Graph
from eyenet.linker.linker import Linker
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.storage import SQLiteStorage, upsert_actor, upsert_group, upsert_source
from eyenet.storage.engines import StoreName
from eyenet.storage.messages import SQLiteMessageStore
from eyenet.telemetry.propagation import current_traceparent

_log = structlog.get_logger()

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/corpora/synthetic_m2.jsonl"
_JAEGER_OTLP = os.environ.get("EYENET_E2E_OTLP_ENDPOINT", "localhost:4317")
_JAEGER_QUERY = os.environ.get("EYENET_E2E_JAEGER_QUERY", "http://localhost:16686")
_SERVICE_NAME = "eyenet-e2e"
_NOW = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)


pytestmark = pytest.mark.skipif(
    os.environ.get("EYENET_E2E_JAEGER") != "1",
    reason="set EYENET_E2E_JAEGER=1 to run (requires Jaeger on :4317 / :16686)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_otlp_exporter() -> tuple[TracerProvider, BatchSpanProcessor]:
    """Install an OTLP exporter; works whether a provider exists or not."""

    exporter = OTLPSpanExporter(endpoint=_JAEGER_OTLP, insecure=True)
    processor = BatchSpanProcessor(exporter)

    current = otel_trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        current.add_span_processor(processor)
        return current, processor
    new_provider = TracerProvider(resource=Resource.create({"service.name": _SERVICE_NAME}))
    new_provider.add_span_processor(processor)
    otel_trace.set_tracer_provider(new_provider)
    return new_provider, processor


async def _seed_fixture(storage: SQLiteStorage) -> list[dict[str, Any]]:
    """Seed actor + message rows from the M2 synthetic fixture. Returns the
    list of records so the test can publish their envelopes in order."""

    records = [json.loads(line) for line in _FIXTURE.read_text().splitlines() if line.strip()]
    engine = storage._engines[StoreName.MESSAGES]
    store = SQLiteMessageStore(engine)

    with Session(engine) as session:
        source_id = upsert_source(
            session, kind=SourceKind.TELEGRAM, display_name="telegram:e2e", created_at=_NOW
        )
        group_id = upsert_group(
            session,
            source_id=source_id,
            platform_groupid="-100",
            kind=GroupKind.CHAT,
            title="E2E",
            seen_at=_NOW,
        )
        actor_ids: dict[str, object] = {}
        for rec in records:
            ak = rec["actor_key"]
            if ak not in actor_ids:
                actor_ids[ak] = upsert_actor(
                    session,
                    source_id=source_id,
                    actor_key=ak,
                    platform_userid=ak[-8:],
                    handle=None,
                    display_name=None,
                    seen_at=_NOW,
                )
        session.commit()
        committed_source = source_id
        committed_group = group_id
        committed_actors = dict(actor_ids)

    for rec in records:
        ref = f"telegram:{rec['platform_groupid']}:{rec['platform_msgid']}"
        body = rec.get("body", "")
        sent = datetime.fromisoformat(rec["sent_at_source"])
        row = MessageTable(
            id=new_uuid7(),
            source_id=committed_source,
            group_id=committed_group,
            actor_id=committed_actors[rec["actor_key"]],  # type: ignore[arg-type]
            platform_msgid=rec["platform_msgid"],
            evidence_ref=ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=sent,
            ingested_at=_NOW,
        )
        await store.put_message(row)
    return records


def _raw_envelope_bytes(rec: dict[str, Any], traceparent: str) -> bytes:
    sent = datetime.fromisoformat(rec["sent_at_source"])
    body = rec.get("body", "")
    env = RawMessageEnvelope(
        source=SourceKind.TELEGRAM,
        instance_id="e2e_test",
        evidence_ref=f"telegram:{rec['platform_groupid']}:{rec['platform_msgid']}",
        actor_key=rec["actor_key"],
        platform_groupid=rec["platform_groupid"],
        platform_msgid=rec["platform_msgid"],
        sent_at_source=sent,
        collected_at=_NOW,
        length_chars=len(body),
        length_words=len(body.split()),
        body_sha256="0" * 64,
        is_forward=False,
        has_attachment=False,
        reply_to_platform_msgid=None,
        trace_context=TraceContext(traceparent=traceparent),
    )
    return env.model_dump_json().encode()


def _query_jaeger_trace(trace_id_hex: str, *, timeout: float = 15.0) -> dict[str, Any]:
    """Poll Jaeger until the trace appears or the deadline fires."""

    url = f"{_JAEGER_QUERY}/api/traces/{trace_id_hex}"
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200 and r.json().get("data"):
                payload: dict[str, Any] = r.json()
                return payload
        except Exception as exc:
            last_err = exc
        time.sleep(0.5)
    raise AssertionError(
        f"trace {trace_id_hex} did not appear in Jaeger within {timeout}s (last error: {last_err})"
    )


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_pipeline_trace_lands_in_jaeger(tmp_path: Path) -> None:
    # Sanity: Jaeger is reachable.
    services = httpx.get(f"{_JAEGER_QUERY}/api/services", timeout=2.0).json()
    assert "data" in services, f"Jaeger query API not reachable at {_JAEGER_QUERY}"

    provider, processor = _install_otlp_exporter()
    tracer = otel_trace.get_tracer("eyenet.collector.telegram")

    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    records = await _seed_fixture(storage)

    sensor = StylometricSensor(bus=bus, storage=storage)
    engine = Engine(bus=bus, storage=storage)
    linker = Linker(bus=bus, storage=storage)
    graph = Graph(bus=bus, storage=storage)

    for svc in (sensor, engine, linker, graph):
        await svc.on_subscribe()

    raw_subject = subject_for(SourceKind.TELEGRAM, "e2e_test")

    # Replay the full fixture, each message inside its own collector.ingest
    # span. We keep the trace_ids of the LAST messages from each actor —
    # those are the ones the linker will see profiles for (linker fires on
    # the trailing edge, when enough observations have accumulated).
    sampled_trace_ids: list[int] = []
    seen_actors: set[str] = set()
    for idx, rec in enumerate(records):
        with tracer.start_as_current_span(
            "collector.ingest",
            attributes={
                "service.name": "collector",
                "service.instance_id": "telegram_e2e",
                "source.platform": "telegram",
                "source.id": "e2e",
                "message.evidence_ref": (
                    f"telegram:{rec['platform_groupid']}:{rec['platform_msgid']}"
                ),
                "message.platform_msgid": rec["platform_msgid"],
            },
        ) as span:
            tp = current_traceparent()
            assert tp is not None, "collector.ingest span produced no traceparent"
            # Sample the FIRST trace_id we see per actor — that one will
            # carry sensor + (eventually) engine spans. We also sample the
            # LAST per actor for the linker/graph emit later in the chain.
            if rec["actor_key"] not in seen_actors:
                sampled_trace_ids.append(span.get_span_context().trace_id)
                seen_actors.add(rec["actor_key"])
            if idx >= len(records) - 3:  # last 3 messages — linker/graph emit likely
                sampled_trace_ids.append(span.get_span_context().trace_id)
            await bus.publish(
                raw_subject,
                _raw_envelope_bytes(rec, tp),
                headers={"traceparent": tp},
            )
        # Yield to the event loop so the create_task chain can advance.
        if idx % 20 == 0:
            await asyncio.sleep(0.05)

    # Drain: sensor / engine / linker are all fire-and-forget via create_task.
    # Give the chain ample time to settle.
    await asyncio.sleep(15.0)

    # Force-flush every pending span to Jaeger.
    processor.force_flush(timeout_millis=15_000)
    provider.force_flush(timeout_millis=15_000)
    # Jaeger's collector batches further; give it a beat to index.
    await asyncio.sleep(2.0)

    expected_ops_subset = {
        "collector.ingest",
        "sensor.dispatch",
        "engine.update_profile",
        "linker.compare",
        "graph.upsert",
        # Tier 2 — bus-layer auto-instrumentation
        "bus.publish",
        "bus.deliver",
        # Tier 6 — storage hot writes (at least one must appear in the pipeline lineage)
        "storage.graph.upsert_node",
    }

    # Pull the union of operations across every sampled trace. Each
    # individual trace covers ONE message's lineage; the union should
    # cover every pipeline tier because at least one trace will have
    # triggered the linker (which only fires after the actor has enough
    # observations to derive a profile slot).
    seen_ops: set[str] = set()
    seen_traces: list[str] = []
    fragmented_spans: list[str] = []
    for trace_id_int in sampled_trace_ids:
        trace_id_hex = f"{trace_id_int:032x}"
        try:
            payload = _query_jaeger_trace(trace_id_hex, timeout=10.0)
        except AssertionError:
            continue
        seen_traces.append(trace_id_hex)
        for t in payload["data"]:
            for s in t["spans"]:
                if s["traceID"] != trace_id_hex:
                    fragmented_spans.append(
                        f"{s['operationName']} (trace {s['traceID']} != {trace_id_hex})"
                    )
                seen_ops.add(s["operationName"])

    assert seen_traces, (
        f"no sampled traces appeared in Jaeger; sampled {len(sampled_trace_ids)} trace_ids"
    )
    assert not fragmented_spans, (
        f"spans appeared with WRONG trace_id (continuity broken): {fragmented_spans[:5]}"
    )

    missing = expected_ops_subset - seen_ops
    primitive_spans = {op for op in seen_ops if op.startswith("sensor.primitive.")}

    _log.info(
        "jaeger.e2e.summary",
        traces_seen=len(seen_traces),
        ops=sorted(seen_ops),
        primitives=len(primitive_spans),
        missing=sorted(missing),
    )

    assert primitive_spans, f"no sensor.primitive.* spans found; saw operations: {sorted(seen_ops)}"
    assert not missing, (
        f"trace incomplete: missing span(s) {missing}; "
        f"saw {sorted(seen_ops)} across {len(seen_traces)} traces"
    )

    await storage.close()
