# Effort scope — incident classifier → bus integration (batched over N)

Measures the work to run `eyenet/incidents/classifier.py` as a live bus service that
classifies monitored-channel messages, batched over N per inference call, and stores
incidents. Grounded in the current architecture (2026-09-26, branch `incidents-ml-pipeline`).

## What already exists (reuse, don't rebuild)
- `eyenet/incidents/classifier.py` — calibrated cascade (`fired_labels()` = model ∪ prefilter),
  model loads once (`lru_cache`), `EYENET_INCIDENT_MODEL_DIR`. **Missing: a batch entry point.**
- Consumer pattern: `StylometricSensor` — `subscribe("raw.message.>", handler, queue_group)`,
  `_process(env)` per message, `put_observations_bulk` for storage batching.
- Async-worker service pattern: M10 `ClassifierService` (document classifier) + `classifier_run`
  CLI stub — same shape, copy the wiring.
- `ServiceBase` + `run_service(tick_interval=…)` — `tick()` is a ready-made flush timer.
- `SIG2LABEL` fusion, per-head thresholds (calibration.json) — done.

## The batching reality (answers "batched on N per bus call")
The bus is **push, per-message** — there is no native batch delivery. Two options:
1. **App-level buffer + flush (lazy path).** Buffer envelopes in the service; flush when
   `len >= N` OR `tick()` fires (time T), whichever first. One `classify_batch` call per flush.
   No bus changes. ~1 day. Time-flush prevents low-traffic starvation.
2. **NATS pull-consumer `fetch(batch=N)` (proper path).** Extend the `Bus` abstraction with a
   pull/fetch API; the service pulls N at a time with native ack/backpressure. Cleaner
   semantics, but touches the bus abstraction (memory + nats backends) and its tests. ~2-3 days.

Recommend option 1 first; option 2 only if ack/backpressure/redelivery guarantees are needed.

## Component breakdown
| # | Component | Effort | Notes |
|---|-----------|--------|-------|
| A | `classify_batch(texts)` — one padded forward pass, calibrated | **S** (~0.5 day) | sweep_ml already does batched inference; lift it |
| B | `IncidentClassifierService(ServiceBase)` — subscribe + buffer + flush(N/T) | **M** (~1 day) | copy StylometricSensor/ClassifierService; the buffer+flush is the only new logic |
| C | Model-in-service (torch/GPU in a long-running proc) | **M** (~0.5 day) | must run unsandboxed near NATS; GPU shared with ollama stage-3 → contention |
| D | `IncidentTable` model + register in `_MAIN_TABLES` + `put_incidents_bulk` repo method | **M** (~0.5-1 day) | BaseRepository + mixin, ANSI-only (no dialect leak); additive table, no wipe |
| E | CLI factory + supervisor spawn wiring | **S-M** (~0.5 day) | `classifier_run` stub + `_factory` branch exist as templates |
| F | Tests (buffer/flush logic, batch classify, DDL, service unit) | **M** (~0.5-1 day) | flush logic is the load-bearing test |

**Total: ~3.5–5 days** for full batched + stored + wired.
**Per-message MVP (skip batching, option-1 buffer later): ~1.5–2 days** — service B in per-message
mode + table D + wiring E, reusing StylometricSensor almost verbatim.

## Risks / decisions
- **Trace propagation + batching conflict.** The rule is `attach_from_headers` per message inside
  `create_task`. Batching breaks the 1:1 span model — decide: one span per message (link into a
  batch span) or a batch-level span. ~0.5 day if per-message spans are required.
- **GPU contention.** The incident model and the stage-3 LLM (ollama) share the 8GB 5060. A
  resident classifier model + ollama may OOM — need a VRAM budget / eviction policy, or CPU
  inference for the classifier (slower but frees GPU for the LLM).
- **Backpressure.** Option 1 has no native ack — if inference lags ingest, the buffer grows.
  Needs a cap + policy (block vs drop-oldest). Option 2 (pull) solves this natively.

## YAGNI check — do you even need batching?
mmBERT-base is ~16 ms/msg single on the 5060; batched (bs 32–64) amortizes to ~3–5 ms/msg.
At small-operator volume (a few collectors), **per-message may be entirely sufficient** —
60+ msg/s single-threaded. Batch only if measured throughput demands it. Recommend: ship the
per-message MVP, measure real ingest rate, add option-1 batching only if it's actually the
bottleneck. Optimal N when needed: 32–64 (sweep_ml ran bs=64 comfortably in 8GB).

## Suggested phasing
1. **Phase 1 (~1.5-2d):** per-message `IncidentClassifierService` + `IncidentTable` + wiring →
   incidents flow and store. Measure ingest rate.
2. **Phase 2 (~1d, if needed):** app-level buffer+flush(N/T) batching + `classify_batch`.
3. **Phase 3 (later):** NATS pull-consumer if ack/backpressure guarantees are required; actor_ops
   → LLM stage-3 route for the uncertain band.
