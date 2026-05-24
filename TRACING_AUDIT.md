# EYENET — Tracing Coverage Audit

**Date:** 2026-05-24
**Scope:** every step from Collector → Sensor → Engine → Linker → Verifier → Graph
**Verdict:** infrastructure is **in place**, but the end-to-end trace is **broken in two structural ways** and has **eight blind spots**. A single bus message does NOT today produce one connected trace from ingest to UI.

---

## 1. THE TWO STRUCTURAL BUGS (fix these first or nothing else matters)

### 1A. Subscribers never extract `traceparent` from bus headers

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

**Fix shape:** at the top of every `_process_*` / `_handle_*` method:

```python
from eyenet.telemetry.propagation import extract
from opentelemetry import context as otel_context

ctx = extract(headers)
token = otel_context.attach(ctx)
try:
    with _tracer.start_as_current_span("engine.update_profile", ...):
        ...
finally:
    otel_context.detach(token)
```

### 1B. `asyncio.create_task` severs context across the dispatch boundary

Every subscriber does the same pattern:

```python
async def _on_obs(subject, payload, headers):
    asyncio.create_task(self._process_observation(subject, payload, headers))
```

Even if 1A is fixed, `create_task` captures the **current** OTel context at scheduling time — which in the bus delivery callback is empty. The extracted context has to be **attached inside the task body**, not before scheduling. (Or use `otel_context.attach(extract(headers))` before `create_task` and pass `context=otel_context.get_current()` through.)

The safer pattern is to extract+attach inside `_process_*` itself, since that's where the span is started.

---

## 2. THE COLLECTOR IS A DEAD-END TRACE ROOT

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

---

## 3. SPAN COVERAGE — WHAT EXISTS vs WHAT'S MISSING

| Stage | Tracer registered | Spans emitted | Missing |
|---|---|---|---|
| **Collector (telegram/matrix real)** | ❌ no | ❌ none | `collector.ingest` per message, `collector.backfill` per cursor batch, `collector.media.fetch` per attachment, `collector.decrypt` (matrix) |
| **Bus (memory/nats)** | ❌ no | ❌ none | `bus.publish` (publish-side), `bus.deliver` (deliver-side, wrapping handler invocation) — PLAN §8.3 explicitly names both |
| **Sensor (stylometric)** | ✓ | `sensor.dispatch` + `sensor.primitive.{name}` per primitive ✓ | Corpus-fetch span (DB read for `requires_full_corpus` primitives), `sensor.publish_observation` |
| **Engine** | ✓ | `engine.update_profile` ✓ | `engine.evaluate_recipes` (winner selection), `engine.emit_candidate` / `engine.emit_current` publish spans |
| **Linker** | ✓ | `linker.compare` (parent) ✓ | `linker.comparator.{name}` per comparator (matches sensor pattern, lets you ask "is the simhash comparator dragging us down?"), `linker.vector.upsert`, `linker.vector.nearest` (the hot path — currently invisible), `linker.persist_proposed`, `linker.publish_proposed` |
| **Verifier** | ✓ | `verifier.evaluate` (parent) ✓ | `verifier.{name}` per verifier (GI, NCD — PLAN §8.4 says we need this; sensor has it, verifier doesn't), `verifier.load_corpus` (the DB hit for actor A and B bodies), `verifier.promote_suspected` publish |
| **Graph** | ✓ | `graph.upsert` on `_on_profile_current` and `_handle_proposed` ✓ | `_handle_suspected`, `_handle_confirmed`, `_handle_rejected`, `_on_persona_updated` — **four out of six graph handlers have no span at all** |
| **Storage** | ❌ no | ❌ none | Every `upsert_*` / `insert_*` / `nearest` / `by_evidence_and_primitive` is untraced. SQLite latency and contention are completely invisible. |
| **Audit (`AuditEmitter`)** | ❌ no | ❌ none | `audit.emit` span wrapping the dual publish+persist write (and recording the hash-chain link as an attribute) |
| **Identity pool** | ❌ no | ❌ none | `identity_pool.lookup`, `identity_pool.label_applied` |
| **Calibration / CLI** | ❌ no | ❌ none | Less critical, but `calibration.run`, `calibration.grid_cell` would let you compare runs |
| **Telemetry setup** | ✓ `eyenet/telemetry/__init__.py` | — | OK |
| **Propagation helper** | ✓ `eyenet/telemetry/propagation.py` | — | OK |
| **Structlog trace-id injection** | ✓ `_add_trace_ids` in `eyenet/telemetry/logging.py` | — | OK |

---

## 4. THE FULL TRACE WE *SHOULD* SEE — ROW BY ROW

For one Telegram message arriving and producing a confirmed linkage, the trace should look like this. Items marked **✗** are missing today.

```
collector.ingest                         ✗ MISSING (no span)
├── collector.media.fetch                ✗ MISSING
├── storage.message.insert               ✗ MISSING
├── bus.publish raw.message.*            ✗ MISSING
│
└── bus.deliver raw.message.*            ✗ MISSING (and ctx not propagated)
    └── sensor.dispatch                  ✓
        ├── sensor.primitive.length      ✓
        ├── sensor.primitive.mattr       ✓
        ├── sensor.primitive.simhash.*   ✓
        ├── sensor.corpus.fetch          ✗ MISSING
        └── bus.publish observation.*    ✗ MISSING
            │
            └── bus.deliver observation.*  ✗ MISSING (ctx broken)
                └── engine.update_profile   ✓
                    ├── storage.observations.by_evidence  ✗
                    ├── storage.profiles.upsert_current   ✗
                    ├── engine.evaluate_recipes           ✗
                    └── bus.publish profile.current       ✗
                        │
                        ├── bus.deliver → linker.compare  ✓ (ctx broken)
                        │   ├── linker.comparator.simhash      ✗
                        │   ├── linker.vector.upsert           ✗
                        │   ├── linker.vector.nearest          ✗ ← HOT PATH, INVISIBLE
                        │   ├── storage.linkages.insert_proposed ✗
                        │   └── bus.publish linkage.proposed   ✗
                        │       │
                        │       ├── bus.deliver → verifier.evaluate  ✓ (ctx broken)
                        │       │   ├── verifier.load_corpus      ✗
                        │       │   ├── verifier.gi               ✗ ← per-verifier missing
                        │       │   ├── verifier.ncd              ✗
                        │       │   └── bus.publish linkage.suspected ✗
                        │       │
                        │       └── bus.deliver → graph.upsert (proposed)  ✓ (ctx broken)
                        │
                        └── bus.deliver → graph.upsert (profile)   ✓ (ctx broken)
```

Out of ~30 expected spans across the pipeline, **~10 exist**, and they're **disconnected** from each other because of §1.

---

## 5. RECOMMENDED FIX ORDER (smallest blast radius first)

1. **Subscriber-side `extract` + `attach`** — single helper in `eyenet/telemetry/propagation.py` (e.g. `attach_from_headers(headers) -> Token`) and one call at the top of every `_process_*` / `_on_*` body. ~10 files, mechanical. **Unlocks every other improvement** because now child spans actually parent to the upstream span.
2. **Bus-layer spans** — add `bus.publish` to `BusEnvelopePublisher.publish` and `bus.deliver` to `MemoryBus._invoke` + the NATS subscribe callback. Auto-instruments every service for free.
3. **Collector spans** — `collector.ingest` in both `telegram/real.py:_ingest_msg` and `matrix/real.py:_handle_*_event`. Makes the trace actually start where the message enters EYENET.
4. **Graph fill-in** — span on the four missing handlers (`suspected`, `confirmed`, `rejected`, `persona_updated`). One copy-paste each.
5. **Per-verifier spans** — mirror the sensor's `sensor.primitive.{name}` pattern with `verifier.{name}`. PLAN §8.4 implies this is required.
6. **Storage spans** — wrap the hot writes (`linkages.insert_proposed`, `vectors.nearest`, `vectors.upsert_simhash`, `profiles.upsert_current`, `graph.upsert_*`, `messages.insert`). The simhash neighbor search alone is worth instrumenting on its own.
7. **AuditEmitter span** — wraps the dual publish+persist and records `audit.hash_chain_prev` as a span attribute.

Steps 1–3 are the difference between "we have trace decorations" and "we have a working end-to-end trace." Everything else is depth.

---

## 6. THINGS THE INFRA GETS RIGHT (credit where due)

- W3C propagation is the right standard.
- The `TraceContext` envelope field + `BusEnvelopePublisher` enforcement is the right design — it forces every envelope to declare its trace lineage.
- `_add_trace_ids` structlog processor means trace/span IDs follow every log line for free, once spans actually exist and are linked.
- Sensor's per-primitive span design is the model the verifier should copy.
- PLAN §8.3 / §8.4 / §8.6 already document the target taxonomy and the sampling-predicate seam — the gap is implementation, not design.
