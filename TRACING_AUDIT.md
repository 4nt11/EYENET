# EYENET — Tracing Coverage Audit

**Date:** 2026-05-24
**Scope:** every step from Collector → Sensor → Engine → Linker → Verifier → Graph

> **Status update — 2026-05-24, commit `911e423`:** the two structural bugs (§1A and §1B) and the collector dead-end (§2) are **FIXED**. A single bus message now produces ONE connected trace from `collector.ingest` through `graph.upsert` with one `trace_id` across ~40 spans, verified against a live Jaeger instance. Tier 4+ depth fill-in remains deferred (see §5).

**Original verdict (pre-fix):** infrastructure is **in place**, but the end-to-end trace is **broken in two structural ways** and has **eight blind spots**. A single bus message does NOT today produce one connected trace from ingest to UI.

---

## 1. THE TWO STRUCTURAL BUGS — ✅ FIXED (commit `911e423`)

### 1A. Subscribers never extract `traceparent` from bus headers — ✅ FIXED

`eyenet/telemetry/propagation.py` exports `extract()`. **Nothing in the codebase calls it.**

Every subscriber handler signature receives `headers: dict[str, str]` and then discards them:

| File | Handler | Headers param |
|---|---|---|
| `eyenet/sensor/stylometric.py:73` | `_handler` | `_headers` (unused) |
| `eyenet/engine/engine.py:69` | `_on_obs` → `_process_observation` | `_headers` (unused) |
| `eyenet/linker/linker.py:70` | `_on_profile` → `_process_profile` | `_headers` (unused) |
| `eyenet/graph/graph.py:62–64` | `_on_profile_current`, `_on_linkage_event`, `_on_persona_updated` | `_headers` (unused) |
| `eyenet/verifier/service.py` | `_on_proposed` → `_process_proposed` | `_headers` (unused) |

Consequence: publishers correctly **inject** `traceparent` (`publisher.py:60`), the bus correctly **carries** it, and subscribers correctly **throw it away**. Every service's span becomes a **new root**. The trace is fragmented at every bus hop.

**Fix shipped:** `eyenet/telemetry/propagation.py::attach_from_headers` (context manager). Wired into every subscriber: sensor `_dispatch`, engine `_process_observation`, linker `_process_profile`, graph `_on_profile_current` / `_on_linkage_event` / `_on_persona_updated`, verifier `_process_proposed`.

### 1B. `asyncio.create_task` severs context across the dispatch boundary — ✅ FIXED

Every subscriber does the same pattern:

```python
async def _on_obs(subject, payload, headers):
    asyncio.create_task(self._process_observation(subject, payload, headers))
```

Even if 1A is fixed, `create_task` captures the **current** OTel context at scheduling time — which in the bus delivery callback is empty. The extracted context has to be **attached inside the task body**, not before scheduling. (Or use `otel_context.attach(extract(headers))` before `create_task` and pass `context=otel_context.get_current()` through.)

The safer pattern is to extract+attach inside `_process_*` itself, since that's where the span is started.

**Fix shipped:** `attach_from_headers(headers)` is invoked inside the `create_task` target (the `_process_*` body), so it runs after `create_task` has scheduled it — the context attaches in the spawned coroutine, not in the calling handler.

---

## 2. THE COLLECTOR IS A DEAD-END TRACE ROOT — ✅ FIXED

`telegram/real.py:358` and `matrix/real.py:{763,1017,1152}` all do:

```python
traceparent = current_traceparent() or _zero_traceparent()
```

There is **no active span** when `_ingest_msg` runs — no `with _tracer.start_as_current_span(...)` anywhere in either collector. So `current_traceparent()` returns `None` every single time, and **every trace begins with an all-zero traceparent**. The trace doesn't start at the collector; it starts nowhere.

**Fix:** wrap each ingestion in a `collector.ingest` span that becomes the trace root. The PLAN §8.3 taxonomy already names this span — it just isn't implemented.

```python
with _tracer.start_as_current_span(
    "collector.ingest",
    attributes={
        "service.name": self.name,
        "service.instance_id": self.instance_id,
        "source.platform": "telegram",  # or "matrix"
        "source.id": str(source_id),
        "message.platform_msgid": platform_msgid,
        "message.evidence_ref": evidence_ref,
    },
):
    ... existing ingest body ...
```

The collector files do not even `get_tracer()`. Zero tracing instrumentation in `eyenet/collectors/**`.

**Fix shipped:**
- `eyenet/collectors/telegram/real.py`: module-level `_tracer = trace.get_tracer("eyenet.collector.telegram")`; `collector.ingest` span wraps `_ingest_msg` (via `_ingest_msg_inner` extraction so attributes can be set mid-body).
- `eyenet/collectors/matrix/real.py`: `_tracer = trace.get_tracer("eyenet.collector.matrix")`; `collector.ingest` spans wrap `_ingest_event` (text), `_ingest_media_event` (media), and `_emit_decrypt_sentinel` (decrypt failures) — each with a `message.kind` attribute so Jaeger filters cleanly.

The `_zero_traceparent()` fallback was deliberately retained as a defensive default for the tracing-disabled case (see §4 below).

---

## 3. SPAN COVERAGE — WHAT EXISTS vs WHAT'S MISSING

Status column legend: ✅ shipped this session · ✓ already present · ❌ still missing (deferred).

| Stage | Tracer | Status | Spans emitted | Still missing |
|---|---|---|---|---|
| **Collector (telegram/matrix real)** | ✅ | ✅ | `collector.ingest` per text/media/decrypt-sentinel | `collector.backfill` per cursor batch, `collector.media.fetch` per attachment |
| **Bus (memory/nats)** | ❌ | ❌ | none | `bus.publish` / `bus.deliver` (PLAN §8.3) |
| **Sensor (stylometric)** | ✓ | ✓ | `sensor.dispatch` + `sensor.primitive.{name}` (per primitive) | Corpus-fetch span, `sensor.publish_observation` |
| **Engine** | ✓ | ✓ | `engine.update_profile` | `engine.evaluate_recipes`, `engine.emit_candidate` / `engine.emit_current` |
| **Linker** | ✓ | ✓ | `linker.compare` (parent) | `linker.comparator.{name}`, `linker.vector.upsert`, `linker.vector.nearest`, `linker.persist_proposed`, `linker.publish_proposed` |
| **Verifier** | ✓ | ✓ | `verifier.evaluate` (parent) | `verifier.{name}` per verifier, `verifier.load_corpus`, `verifier.promote_suspected` |
| **Graph** | ✓ | partial | `graph.upsert` on `_on_profile_current` and `_handle_proposed` | `_handle_suspected`, `_handle_confirmed`, `_handle_rejected`, `_on_persona_updated` |
| **Trace propagation across bus hops** | — | ✅ | `attach_from_headers` wired into every subscriber | — |
| **Tracing off-switch** | — | ✅ | `EYENET_TRACING_DISABLED` / `OTEL_SDK_DISABLED` env var | — |
| **Storage** | ❌ | ❌ | none | All `upsert_*` / `insert_*` / `nearest` / `by_evidence_and_primitive` |
| **Audit (`AuditEmitter`)** | ❌ | ❌ | none | `audit.emit` wrap |
| **Identity pool** | ❌ | ❌ | none | `identity_pool.lookup`, `identity_pool.label_applied` |
| **Calibration / CLI** | ❌ | ❌ | none | `calibration.run`, `calibration.grid_cell` |
| **Telemetry setup** | ✓ | ✓ | `eyenet/telemetry/__init__.py` | — |
| **Propagation helper** | ✓ | ✅ extended | `extract`, `inject`, `current_traceparent`, **`attach_from_headers`** | — |
| **Structlog trace-id injection** | ✓ | ✓ | `_add_trace_ids` in `eyenet/telemetry/logging.py` | — |

---

## 4. THE FULL TRACE WE *SHOULD* SEE — ROW BY ROW

For one Telegram message arriving and producing a confirmed linkage, the trace should look like this. Status legend: **✓** shipped (connected), **✗** still missing (deferred).

```
collector.ingest                         ✓ SHIPPED (root)
├── collector.media.fetch                ✗ deferred
├── storage.message.insert               ✗ deferred
├── bus.publish raw.message.*            ✗ deferred (tier 4)
│
└── bus.deliver raw.message.*            ✗ deferred (tier 4)
    └── sensor.dispatch                  ✓ + CONNECTED via attach_from_headers
        ├── sensor.primitive.length      ✓ + CONNECTED
        ├── sensor.primitive.mattr       ✓ + CONNECTED
        ├── sensor.primitive.simhash.*   ✓ + CONNECTED
        ├── sensor.corpus.fetch          ✗ deferred
        └── bus.publish observation.*    ✗ deferred (tier 4)
            │
            └── bus.deliver observation.*  ✗ deferred (tier 4)
                └── engine.update_profile   ✓ + CONNECTED
                    ├── storage.observations.by_evidence  ✗ deferred
                    ├── storage.profiles.upsert_current   ✗ deferred
                    ├── engine.evaluate_recipes           ✗ deferred
                    └── bus.publish profile.current       ✗ deferred (tier 4)
                        │
                        ├── bus.deliver → linker.compare  ✓ + CONNECTED
                        │   ├── linker.comparator.simhash      ✗ deferred
                        │   ├── linker.vector.upsert           ✗ deferred
                        │   ├── linker.vector.nearest          ✗ deferred ← HOT PATH
                        │   ├── storage.linkages.insert_proposed ✗ deferred
                        │   └── bus.publish linkage.proposed   ✗ deferred (tier 4)
                        │       │
                        │       ├── bus.deliver → verifier.evaluate  ✓ + CONNECTED
                        │       │   ├── verifier.load_corpus      ✗ deferred
                        │       │   ├── verifier.gi               ✗ deferred ← per-verifier
                        │       │   ├── verifier.ncd              ✗ deferred
                        │       │   └── bus.publish linkage.suspected ✗ deferred
                        │       │
                        │       └── bus.deliver → graph.upsert (proposed)  ✓ + CONNECTED
                        │
                        └── bus.deliver → graph.upsert (profile)   ✓ + CONNECTED
```

**Result, verified against live Jaeger (trace `5cd2502c3b3b8f3a84ae59092153ab6d`, 2026-05-24):** one root, 40 spans, single `trace_id`. Tier coverage: collector ×1, sensor.dispatch ×1, sensor.primitive.* ×21, engine.update_profile ×5, linker.compare ×2, graph.upsert ×10. The "still missing" items are span-depth fill-in (tiers 4–7 below) — the **end-to-end propagation chain is unbroken**.

---

## 5. FIX ORDER — STATUS

1. ✅ **Subscriber-side `extract` + `attach`** — DONE. `attach_from_headers` context manager shipped in `eyenet/telemetry/propagation.py`; wired into every subscriber inside the `create_task` target. (Commit `911e423`.)
2. ❌ **Bus-layer spans** — deferred. Add `bus.publish` to `BusEnvelopePublisher.publish` and `bus.deliver` to `MemoryBus._invoke` + the NATS subscribe callback. Auto-instruments every service for free.
3. ✅ **Collector spans** — DONE. `collector.ingest` in `telegram/real.py:_ingest_msg`, `matrix/real.py:_ingest_event` / `_ingest_media_event` / `_emit_decrypt_sentinel`. Trace now starts where the message enters EYENET.
4. ❌ **Graph fill-in** — deferred. Span on the four missing handlers (`suspected`, `confirmed`, `rejected`, `persona_updated`). One copy-paste each.
5. ❌ **Per-verifier spans** — deferred. Mirror the sensor's `sensor.primitive.{name}` pattern with `verifier.{name}`. PLAN §8.4 implies this is required.
6. ❌ **Storage spans** — deferred. Wrap the hot writes (`linkages.insert_proposed`, `vectors.nearest`, `vectors.upsert_simhash`, `profiles.upsert_current`, `graph.upsert_*`, `messages.insert`).
7. ❌ **AuditEmitter span** — deferred. Wraps the dual publish+persist and records `audit.hash_chain_prev` as a span attribute.

**Bonus shipped this session:**
- `EYENET_TRACING_DISABLED` / `OTEL_SDK_DISABLED` env-var off-switch in `init_telemetry`.
- Unit + per-service continuity test suite (`tests/integration/test_trace_continuity.py`).
- E2E Jaeger test gated by `EYENET_E2E_JAEGER=1` (`tests/e2e/test_jaeger_trace_continuity.py`).

Steps 1, 3 (and the off-switch) closed in this session — the difference between "we have trace decorations" and "we have a working end-to-end trace." Steps 2, 4–7 are depth fill-in: useful, not urgent.

---

## 6. THINGS THE INFRA GETS RIGHT (credit where due)

- W3C propagation is the right standard.
- The `TraceContext` envelope field + `BusEnvelopePublisher` enforcement is the right design — it forces every envelope to declare its trace lineage.
- `_add_trace_ids` structlog processor means trace/span IDs follow every log line for free, once spans actually exist and are linked.
- Sensor's per-primitive span design is the model the verifier should copy.
- PLAN §8.3 / §8.4 / §8.6 already document the target taxonomy and the sampling-predicate seam — the gap is implementation, not design.
