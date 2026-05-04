# EYENET — Design Document (v0)

> *"Don't look. Observe."*
>
> EYENET is the **attribution engine** sibling of DECNET, and the **consumer** of the BEHAVE-TEXT observation framework. Where BEHAVE-TEXT measures, EYENET concludes.

---

## 1. Mission & Scope

EYENET observes threat actors across chat-style channels (Telegram first; forums, IRC, Matrix, Discord later) and produces:

- **Actor profiles** (stylometric + lexicometric signatures, role classification).
- **Linkage proposals** (cross-account, cross-platform identity links).
- **Threat graphs** over the relation set:
  - Actor ↔ Actor (intra-platform and cross-platform)
  - Actor ↔ Group
  - Group ↔ Group
  - Message ↔ Message (quote/reply/forward chains)
  - Actor ↔ Infrastructure (handles, wallets, PGP keys, domains)

EYENET does **not** redefine BEHAVE-TEXT primitives. It consumes `actor.observation.text.*` envelopes and emits `attribution.*` events.

**Out of scope (v0):** active engagement, takedown coordination, automated reporting to platforms.

---

## 2. Architecture — service map

```
   ┌─────────────┐  raw msg     ┌─────────┐ observation    ┌────────┐
   │ Collectors  ├─────────────▶│ Sensors ├───────────────▶│ Engine │
   │  (fleet)    │ raw.message.*│ (fleet) │actor.obs.text.*│        │
   └──────┬──────┘              └─────────┘                └────┬───┘
          │                                                     │ attribution.profile.*
   ┌──────▼──────┐                                              ▼
   │ Identity    │                                         ┌─────────┐
   │ Pool        │                                         │ Linker  │
   └─────────────┘                                         └────┬────┘
                                                                │ attribution.linkage.proposed
                                                                ▼
                                                           ┌─────────┐
                                                           │  Graph  │
                                                           └─────────┘
```

| Tier | Responsibility | Cardinality | Consumes | Emits |
|---|---|---|---|---|
| **Collectors** | Pull raw messages from a source. One process per `(source, identity)` pair. | 1..N | (external) | `raw.message.{source}.{instance}` |
| **Sensors** | Run BEHAVE-TEXT primitives over raw messages. Stateless workers; horizontal-scaled by primitive group. | 1..N | `raw.message.*` | `actor.observation.text.*` |
| **Engine** | Aggregate observations into actor profiles. | 1 (sharded by `actor_id` later) | `actor.observation.text.*`, `identity.label.applied` | `attribution.profile.candidate`, `attribution.profile.current` |
| **Linker** | Compute cross-actor similarity, propose identity links. | 1 (sharded later) | `attribution.profile.current` | `attribution.linkage.proposed` |
| **Graph** | Persist nodes/edges; serve graph queries. | 1 | `attribution.profile.*`, `attribution.linkage.*` | (query API) |

**Cardinality is a first-class concern.** Collectors and Sensors are designed as fleets from day one — every interface assumes N instances. Engine, Linker, Graph start as singletons but their consumer-group subscriptions are designed so sharding is an ops change, not a redesign.

All services are independent processes communicating over the bus. No service holds a reference to another service's storage.

### 2.1 Collector fleet

**Scoping rule (small-operator friendly):** *One collector process owns one identity, and one identity covers as many groups/channels/forums/threads as that identity has access to.* We do **NOT** spawn a process per Telegram group, per forum thread, or per chat. That would be enterprise-shaped overkill and EYENET is built for the little guy. A single `TelegramCollector` instance with identity `tg_alpha` handles ALL channels `tg_alpha` is joined to, multiplexing them onto the bus.

Plurality exists for two — and only two — reasons:
1. **Multiple identities** on the same source (e.g. two Telegram accounts to widen visibility / reduce per-account rate-limit exposure).
2. **Multiple sources** on the same operator (Telegram + a forum + Matrix).

A typical small-team deployment is 1–3 collector processes total. The fleet abstraction exists so that *3 doesn't require redesign to become 5*, not so we shard everything.

- **`CollectorBase`** defines the abstract factory; concrete implementations: `TelegramCollector` (v0), `MatrixCollector`, `IRCCollector`, `DiscordCollector`, `ForumCollector` (HTTP-scrape), `RSSCollector`, etc.
- A **Collector Supervisor** is **deferred** until the fleet exceeds ~3 processes. v0 ships without one — the operator launches collectors manually (systemd units or `nohup`).
- Collectors emit on `raw.message.{source}.{instance_id}`. The `instance_id` is derived from a hash of the identity, never the identity itself. Subscribers downstream filter on `{source}` (e.g. `raw.message.telegram.>`), not on per-chat granularity.

### 2.2 Sensor fleet

- Sensors are **stateless** (no per-actor state — that's the Engine's job). They subscribe to `raw.message.>` as a NATS *queue group*, so messages are load-balanced across sensor instances.
- **v0 ships ONE sensor process running all primitives.** Splitting by primitive group (`stylometric-sensor`, `lexical-sensor`) is allowed but only earns its keep when a primitive becomes expensive enough to need its own process — small-operator deployments will likely never need this. The queue-group design means scaling out is "launch a second sensor"; no redesign required.

---

## 3. Bus — NATS

- **Transport:** NATS core (pub/sub) for v0. JetStream enabled for durable streams when replay is needed (Engine restart, Linker reprocessing, Graph rebuild).
- **Deployment:** single `nats-server -js` binary. Embedded in-process for dev fixtures; standalone for prod.
- **Abstract factory:** `Bus` interface with `publish(subject, payload)`, `subscribe(subject, handler, queue_group=None)`, `request(subject, payload, timeout)`. NATS is the only implementation in v0; the interface exists so we can swap if NATS fails us.
- **Subjects (topic taxonomy):**
  - `raw.message.{source}.{instance_id}` — raw collected messages (ref to message store, not body).
  - `actor.observation.text.{primitive_namespace}` — BEHAVE-TEXT observations (`stylometric`, `lexical`, `temporal_evolution`, `interaction`, `network`, `content`).
  - `identity.label.applied` — user-supplied ground-truth labels.
  - `identity.engagement.authorized` — user-authorized engagement registry.
  - `attribution.profile.candidate` — engine-emitted candidate profile.
  - `attribution.profile.current` — engine-emitted current best profile per actor.
  - `attribution.linkage.proposed` — linker-emitted cross-actor link proposals.
  - `eyenet.audit.{service}` — internal audit log stream (see §9 Logging).
  - `eyenet.control.{service}.{instance_id}` — control plane (e.g. `eyenet.control.collector.tg_alpha.shutdown`).

---

## 4. Contracts (CDD core)

EYENET is **Contract-Driven**. Every inter-service exchange is defined as a versioned schema BEFORE the producing or consuming service is implemented. Tests are written against the contract, not the implementation.

### 4.1 Contract artifacts

- **Location:** `/contracts/` directory at repo root.
- **Format:** Pydantic v2 models + JSON Schema export (machine-readable for non-Python consumers).
- **Versioning:** `schema_version` field is **mandatory** on every envelope. Breaking changes increment major; additive changes increment minor. Old versions remain valid for one major cycle.
- **Source of truth for observations:** `decnet_behave_text.spec.Observation`. We import it; we do **not** redefine it.

### 4.2 Contract list (v0)

| Contract | Owner | File |
|---|---|---|
| `RawMessage` | EYENET | `contracts/raw_message.py` |
| `Observation` (re-export) | BEHAVE-TEXT | imported |
| `IdentityLabel` | EYENET | `contracts/identity.py` |
| `EngagementAuthorization` | EYENET | `contracts/identity.py` |
| `ProfileCandidate` | EYENET | `contracts/attribution.py` |
| `ProfileCurrent` | EYENET | `contracts/attribution.py` |
| `LinkageProposed` | EYENET | `contracts/attribution.py` |
| `Bus` interface | EYENET | `contracts/bus.py` |
| `Storage` interface | EYENET | `contracts/storage.py` |
| `IdentityPool` interface | EYENET | `contracts/identity_pool.py` |
| `CollectorBase` interface | EYENET | `contracts/collector.py` |
| `SensorBase` interface | EYENET | `contracts/sensor.py` |

### 4.3 Evidence handling (operator-grade, not consumer-privacy)

EYENET is an **attribution tool for operators**. Stylometric primitives without target/intent context produce a beautifully-engineered paperweight — you'd know *how* an actor writes but not *what* they're trying to attack. So:

- **The message store retains full content.** Body, attachments-meta, quoted/forwarded chains, all of it. Encrypted at rest (age, key in operator's keyring), access-audited.
- **`evidence_ref` is a dereferenceable handle**, not a privacy fence. Engine, Linker, Graph and the operator UI/CLI **can and should** resolve it to the actual message when context is needed for profiling, linkage scoring, or operator review.
- **Bus envelopes still carry hashes/aggregates, not bodies** — but only because (a) the bus is high-fanout and bodies don't belong on every subscriber's wire, and (b) `decnet_behave_text.spec.Observation` defines that shape and we don't redefine it. This is a *transport* choice, not a *security* choice. Anything downstream that needs the body fetches it from `MessageStore` by `evidence_ref`.
- **Actor identifiers are opaque hashes (`actor:<sha256(platform||handle)>`)** for stable cross-service referencing and join keys. The platform handle, display name, and any other actor-side metadata live in the message store and are freely retrievable. This is a join-key convention, not a privacy mechanism.
- **Audit, don't restrict.** Every dereference of `evidence_ref` outside the Sensor produces an audit event (`eyenet.audit.evidence_access`) carrying `service`, `instance_id`, `operator_id` if applicable, `evidence_ref`, `reason`. Operators can read everything; we just record who looked at what and why.
- **Targeting/intent context is a first-class observation namespace.** The BEHAVE-TEXT `content.*` group (`targeting_language`, `transactional_language`, `boasting_pattern`, etc.) is exactly the bridge from "how they write" to "what they're after". We index it, profile against it, and graph it. The experimental caveat from BEHAVE-TEXT applies — weight skeptically — but we use it.

### 4.4 What we still don't put on the bus

The constraints that *do* survive are mechanical, not ideological:

- Don't publish full message bodies on `actor.observation.text.*` — that subject is shaped by BEHAVE-TEXT's `Observation` envelope and bodies don't fit. Use `evidence_ref`.
- Don't put the operator's own identity-pool secrets (session files, proxy creds) on the bus, ever. Those live on disk, encrypted, per-collector.
- Don't put age/encryption keys on the bus. Operator's keyring only.

---

## 5. Storage

### 5.1 Tiers

| Tier | Contents | Backend (v0) | Retention |
|---|---|---|---|
| **Hot** | Active corpora, open profiles, recent observations, graph state | SQLite + sqlite-vec | indefinite while open |
| **Cold** | Closed-case messages, historical observations | Compressed NDJSON / Parquet on disk | configurable, default 1 year |
| **Archived** | Evidence-grade, encrypted (age) | Out-of-band volume | indefinite, manual access |

### 5.2 Storage interface (abstract factory)

`Storage` interface with separate sub-interfaces:
- `MessageStore` — raw messages by `evidence_ref`.
- `CorpusStore` — append-only per-actor message history.
- `ObservationStore` — observations indexed by `(actor_id, primitive, ts)`.
- `ProfileStore` — current + historical profile states.
- `VectorIndex` — similarity search over hash/vector primitives (sqlite-vec for TF-IDF; flat SQL Hamming for simhashes until ~1M signatures).
- `GraphStore` — nodes + edges with typed relations.

v0 implementation: **all backed by SQLite** in separate database files, one per concern. Migration to Postgres + pgvector + Neo4j when scale forces it; the abstract factory pays for itself there.

### 5.3 Per-actor corpus

Append-only. Each row: `(actor_id, ts, evidence_ref, message_length, language)`. Sensor reads incrementally (cursor by `ts`) so the engine never re-processes the full corpus on update.

---

## 6. Identity Pool & OPSEC

### 6.1 Pool design

- Pool config: `identities.toml` outside the repo (gitignored, age-encrypted at rest).
- Each entry: session file path, proxy/Tor circuit ID, device fingerprint hash, cooldown window, last-used timestamp.
- A collector instance **claims** an identity for the duration of its run — rotation mid-session is itself a fingerprint.
- Identity isolation is enforced by separate working directories per identity; no shared state between collector processes.

### 6.2 Collector OPSEC rules

- No two identities share an outbound IP simultaneously.
- Cooldown windows respected (default 6h between sessions for same identity).
- Telegram-specific: TDLib database file is per-identity, never shared.
- Operator-tier kill switch: publishing to `eyenet.control.collector.*.shutdown` halts collectors and rotates pool state to "frozen". A global `EYENET_PANIC=1` env or `eyenet.control.global.panic` does the same fleet-wide.

---

## 7. Testing Strategy

CDD-aligned, four layers.

### 7.1 Contract tests (gate)

- Every contract has a property-based test suite (Hypothesis) verifying:
  - Round-trip serialize/deserialize.
  - Schema-version compatibility (v_n consumer accepts v_n and v_{n-1} producers within the major).
  - Required-field exhaustiveness.
- **Gate:** no service merges without passing the contract tests for every contract it touches.

### 7.2 Service unit tests

- Each service tested in isolation with the bus mocked (the `Bus` interface makes this trivial).
- Collector: source SDK mocked; assert `RawMessage` envelopes emitted are well-formed and carry the correct `instance_id`.
- Sensor: deterministic input message → expected observation envelope.
- Engine: sequence of observations → expected profile transition.
- Linker: pair of profiles → expected linkage score and decision.

### 7.3 Integration tests (in-memory bus)

- Use embedded NATS or a `MemoryBus` implementation of the `Bus` interface.
- Run two-or-more services together over a fixture corpus.
- **Multi-collector tests are first-class:** spin up 2+ collectors with distinct identities, verify no `instance_id` collisions, no shared state, no cross-talk on outbound network mocks.
- Verify end-to-end topic flow: `raw.message.*` → `actor.observation.text.*` → `attribution.profile.*` → `attribution.linkage.proposed` → graph state.

### 7.4 End-to-end tests (NATS standalone)

- Spawn a real `nats-server -js` (testcontainers or local binary).
- Run all services as separate processes.
- Replay a recorded fixture corpus (sanitized Rutify subset, redacted).
- Assert eventual graph state matches the expected snapshot.

### 7.5 Fixture corpora

- `tests/fixtures/corpora/synthetic_*.jsonl` — generated, deterministic, no PII.
- `tests/fixtures/corpora/rutify_redacted.jsonl` — small, hand-redacted ground-truth subset (under access control; `.gitignore`d).
- Generated personas with known stylometric signatures for ground-truth attribution tests.

### 7.6 Stylometric calibration tests

Separate test class (`tests/calibration/`), excluded from default `pytest`:
- Within-author Hamming distance distribution.
- Cross-author Hamming distance distribution.
- AUC for each primitive's discrimination power on the labeled corpus.
- Regression budget: a primitive's discrimination AUC may not drop more than 5% across a release.

---

## 8. Tracing Strategy

> **Tracing is developer/debug instrumentation in v0.** It is full-fat, 100%-sampled, and rich. Performance cost is accepted in exchange for being able to debug any of the 20+ primitives in isolation. We can dial it back when the primitive suite is stable; not before.

### 8.1 Layered, accumulating context

The trace is a **vertical lineage** that grows as the message moves up the stack. Every service inherits the parent's span context **and adds its own attributes** on a new child span. By the time a `attribution.linkage.proposed` event lands in the graph, its trace tree carries — readable end-to-end — every fact that produced it: which message, from which group, fetched by which collector identity, sensed by which primitives with which intermediate values, profiled into which delta, scored against which other actor.

If anything breaks at any layer, the trace tells you **which message, which primitive, which input** caused it. No bisection. No "which of the 20 primitives is silently returning garbage today?"

### 8.2 Trace propagation

- Every envelope on the bus carries a `trace_context` field (W3C `traceparent` + `tracestate`).
- The Collector **starts the root span** at message fetch. Every downstream service's first action on receiving an envelope is to extract `traceparent` and open a child span under it.
- Span links (not just parent-child) are used when a service merges multiple inputs (e.g. Linker comparing two actors → one span with links to both source-profile spans).

### 8.3 Span taxonomy — full attribute lists

#### `collector.fetch` — root span
| Attribute | Example | Notes |
|---|---|---|
| `service.name` | `collector` | constant |
| `service.instance_id` | `tg_alpha_8f3c` | hash-derived, never the raw identity |
| `collector.source` | `telegram` | source type |
| `collector.identity_hash` | `<sha256>` | for correlation, not the identity itself |
| `collector.proxy_circuit` | `tor:circuit_id` | optional, opaque |
| `source.chat_id` | `-1001234567890` | Telegram chat / forum thread id |
| `source.chat_title` | `"Rutify Buyers"` | human-readable; helpful for triage |
| `source.chat_type` | `group`, `channel`, `dm`, `forum_thread` | |
| `message.id` | `12345` | platform-native message id |
| `message.evidence_ref` | `telegram:-1001234567890:12345` | dereferenceable handle |
| `message.length_chars` | `247` | |
| `message.length_words` | `42` | |
| `message.has_attachment` | `true`/`false` | |
| `message.is_forward` | `true`/`false` | |
| `message.reply_to_id` | `12340` | nullable |
| `actor.id` | `actor:<sha256(telegram\|\|userid)>` | opaque join key |
| `actor.platform_userid` | `1234567` | retained — operator-grade evidence |
| `actor.handle` | `@somehandle` | retained |
| `actor.display_name` | `"Some Name"` | retained |
| `time.message_sent` | ISO8601 | platform timestamp |
| `time.collected` | ISO8601 | when EYENET fetched it |
| `time.lag_seconds` | `12.4` | collected − sent |

#### `sensor.dispatch` — per-message sensor parent span
Wraps the per-primitive children. One per `(message, sensor instance)` pair.

| Attribute | Notes |
|---|---|
| `service.name` | `sensor` |
| `service.instance_id` | `sensor_default` or `stylometric-sensor` etc. |
| `sensor.primitive_count` | how many primitives ran on this message |
| `sensor.corpus_window_size` | sliding window in messages used for this evaluation |
| `sensor.primitives_succeeded` | count |
| `sensor.primitives_failed` | count |
| (inherits) | `actor.id`, `message.evidence_ref` propagated for ergonomic querying |

#### `sensor.primitive.<namespace>.<name>` — per-primitive child span
**One span per primitive computation.** This is the load-bearing span for debuggability: when something breaks among 20+ primitives, you see exactly which one and with what input.

| Attribute | Example | Notes |
|---|---|---|
| `primitive.namespace` | `stylometric`, `lexical`, `interaction`, ... | BEHAVE-TEXT top-level group |
| `primitive.name` | `function_word_distribution_top50` | BEHAVE-TEXT primitive |
| `primitive.version` | `0.2` | implementation version |
| `primitive.value_kind` | `hash`, `numeric`, `enum`, `array` | per BEHAVE-TEXT registry |
| `primitive.value` | `<simhash hex>` or `0.42` or `proper` | the computed observation value |
| `primitive.input_token_count` | `127` | what the primitive saw |
| `primitive.input_corpus_cursor` | `actor:abc:msg_847` | corpus position used |
| `primitive.duration_ms` | `12.7` | for perf hotspots |
| `primitive.cache_hit` | `true`/`false` | when applicable |
| `primitive.warning_codes` | `["short_corpus"]` | non-fatal flags |
| `primitive.outcome` | `ok`, `skipped`, `error` | |
| `primitive.skip_reason` | `corpus_too_short` | when `outcome=skipped` |
| `error.type` / `error.message` | (on error) | exception captured, span marked errored |

**Failure isolation:** a failed primitive marks ITS span as errored and is logged, but **does not abort sibling primitives or the parent `sensor.dispatch` span**. A broken primitive is a known operational hazard — it must not poison its 19 neighbors.

#### `engine.update_profile` — profile delta span
| Attribute | Notes |
|---|---|
| `service.name` | `engine` |
| `actor.id` | |
| `profile.version_before` | |
| `profile.version_after` | |
| `profile.delta.primitives_changed` | array of primitive names that moved |
| `profile.delta.role_signal_before` / `..._after` | role recipe transition if any |
| `profile.candidate_emitted` | `true`/`false` |
| `profile.current_emitted` | `true`/`false` |
| `engine.observations_consumed_this_window` | |

#### `linker.compare` — pairwise comparison span
| Attribute | Notes |
|---|---|
| `service.name` | `linker` |
| `actor.a.id` / `actor.b.id` | |
| `linker.method` | `function_word_simhash_hamming`, `char_ngram_hamming`, `tfidf_cosine`, ... |
| `linker.distance` | numeric |
| `linker.score` | normalized [0,1] |
| `linker.decision` | `link`, `nolink`, `inconclusive` |
| `linker.threshold` | the threshold applied |
| (links) | span-links to both source `engine.update_profile` spans for the two actors |

#### `graph.upsert` — graph mutation span
| Attribute | Notes |
|---|---|
| `service.name` | `graph` |
| `graph.op` | `node_upsert`, `edge_upsert`, `edge_remove` |
| `graph.node_type` / `graph.edge_type` | |
| `graph.node_id` / `graph.edge_id` | |
| `graph.source_event` | `attribution.linkage.proposed` etc. |

### 8.4 Per-primitive failure surface (specific to the 20+ primitive problem)

For every primitive on every message we record:
- A `sensor.primitive.*` span with full input/output attributes.
- A structured log line `event=primitive.evaluated` mirroring the span's key fields (so log-grep works without a trace UI).
- On failure: span errored, log at `error`, sibling primitives continue.

This means: **"primitive X is broken"** becomes a one-query investigation — filter spans by `primitive.name=X AND outcome=error`, see every broken evaluation, every input that broke it, every actor it failed on.

### 8.5 Backend

- v0: local OTLP collector → file (NDJSON spans). Cheap, greppable, no infra.
- v1: Tempo or Jaeger when v0 stops scaling for visualization.

### 8.6 Sampling

- v0: **100% sampling, full attributes.** Tracing is a developer tool right now.
- Future: tail-based sampling — keep all traces where `attribution.linkage.proposed` is emitted or any span is errored; sample the rest.

---

## 9. Logging Strategy

### 9.1 Structured, JSON, single shape

Every log line:

```json
{
  "ts": "2026-05-03T...Z",
  "level": "info",
  "service": "engine",
  "instance_id": "<service-instance-id>",
  "trace_id": "<otel trace id>",
  "span_id": "<otel span id>",
  "event": "profile.updated",
  "actor_id": "actor:<hash>",
  "fields": { ... }
}
```

- No printf-style messages. Event names are dotted, lowercase, stable.
- `actor_id` and other identifiers are always hashed/opaque in logs; the message store is the only place where mapping back is possible (and audited).
- `instance_id` distinguishes log lines from sibling collectors/sensors in a fleet.

### 9.2 Levels

| Level | Use |
|---|---|
| `debug` | Per-message internal state. Off in prod. |
| `info` | Lifecycle events: subscribe, publish, profile update. |
| `warn` | Recoverable: contract version mismatch handled by fallback, identity cooldown hit. |
| `error` | Unrecoverable for the message: dropped envelope, deserialization failure. |
| `audit` | Operator-relevant: identity pool state changes, manual label application, kill-switch trigger. |

### 9.3 Audit log

- Separate stream: `eyenet.audit.{service}` on the bus, persisted to its own NDJSON file with append-only permissions.
- Audit events: identity pool rotation, manual label application, profile override, archive/delete tier transitions, kill-switch, collector start/stop with which identity.
- Audit log is **the** source of truth for "what did an operator do, and when?"

### 9.4 Log routing

- stdout JSON → systemd-journald (or container runtime).
- Audit stream → dedicated file with restricted permissions (`0600`).
- No logs to syslog; no logs to network sinks in v0.

---

## 10. Roadmap

### Milestone 0 — Contracts only (no service code)
- All `contracts/*.py` files written.
- Contract test suite passing.
- This document accepted.

### Milestone 1 — Bus + skeleton services
- NATS factory implementation.
- Each service starts, subscribes, prints "alive", exits cleanly on signal.
- OpenTelemetry tracing wired (context propagation).
- Structured logging in place.

### Milestone 2 — First Telegram collector + sensors
- One Telegram collector instance with one identity from the pool.
- Sensors implement stylometric primitives v0.2 (function_word_top50, character_ngram_simhash, distinctive_vocabulary_signature, MATTR).
- End-to-end: real Telegram channel → observations on bus → SQLite.

### Milestone 2.5 — Multi-collector validation
- Run two Telegram collectors with two distinct identities concurrently.
- Validate no cross-talk, no shared state, separate trace lineages, separate audit entries.

### Milestone 3 — Engine + profiles
- Profile recipes from `attribution-recipes.md` placeholders, starting with `lurker_or_observer` and `bot_or_automated_poster`.
- Profile current/candidate flow.

### Milestone 4 — Linker + graph
- Hamming-distance linker over function-word and character-ngram simhashes.
- Graph store with typed edges.
- Query API (read-only) for operator UI later.

### Milestone 5 — Calibration on Rutify corpus
- Calibration test suite green.
- First written attribution recipes for EYENET (replacing BEHAVE-TEXT placeholder).

### Milestone 6 — Second source
- A second `CollectorBase` implementation (Matrix or Forum). The point is not the source — the point is to *prove the abstract factory holds*.

---

## 11. Open Questions

1. **Graph backend final choice:** Neo4j vs ArangoDB vs SQLite-with-edges. v0 uses SQLite-with-edges for zero-ops; revisit at Milestone 4.
2. **Profile-state representation:** snapshot-per-update vs event-sourced. Leaning event-sourced (audit-friendly), but snapshot is simpler. Decide at Milestone 3.
3. **Cross-platform actor ID:** how do we generate a stable cross-platform actor ID before linkage runs? Currently `actor:<sha256(platform||handle)>` is per-platform; cross-platform ID is the linker's *output*, not its input.
4. **Collector Supervisor:** deferred — manual launch is fine until the fleet exceeds ~3 collectors. Revisit only if real deployments outgrow that.
5. **BEHAVE-SHELL fusion:** if a Telegram actor is also observed in a PTY (BEHAVE-SHELL), can the engine fuse both substrates? Out of scope for v0; flagged for v1.

---

## 12. Non-Goals (v0)

- No automated engagement with actors.
- No active deception / honeypot behavior.
- No automated reporting to platforms.
- No web UI (CLI + graph query API only).
- ~~No multi-tenant operator separation.~~ **Revised (2026-05-04):** multi-user IS in scope as of MODELS.md §2.17 (`SystemUser`). v0 default is single-user, but the model and permission system are designed for N operators from the start. Multi-tenant *isolation* (separate data realms per tenant) remains a non-goal.
