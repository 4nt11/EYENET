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
- **Baseline `health() -> CollectorHealth` is required on `CollectorBase` from day one.** The supervisor is deferred (below), but adding `health()` later forces a retrofit on every concrete collector. `CollectorHealth` reports: `state` (one of `starting`, `running`, `cooling`, `rate_limited`, `degraded`, `stopped`), `identity_name`, `last_message_at`, `messages_in_last_hour`, `current_subscriptions` (e.g. group ids it's tailing), `last_error` (nullable). The shape is part of the `contracts/collector.py` interface and tested by the contract test suite.
- A **Collector Supervisor** is **deferred** until the fleet exceeds ~3 processes. v0 ships without one — the operator launches collectors manually (systemd units or `nohup`). When the supervisor lands, it calls `health()` over the bus (`eyenet.control.collector.{instance_id}.health` request/reply).
- Collectors emit on `raw.message.{source}.{instance_id}`. The `instance_id` is derived from a hash of the identity, never the identity itself. Subscribers downstream filter on `{source}` (e.g. `raw.message.telegram.>`), not on per-chat granularity.
- **`instance_id` construction — pinned.** `instance_id = sha256(identity_name + "::" + source_kind).hexdigest()[:8]` (8 hex chars / 32 bits, collision-safe at fleet sizes ≪1000). **No salt.** The same `(identity_name, source_kind)` MUST produce the same `instance_id` on every operator workstation so audit trails correlate across hosts. The formula is documented in the `contracts/collector.py` interface docstring and asserted by a contract test that fixes a known input/output pair. Two collector implementations diverging on this hash silently breaks bus-subject filtering and OPSEC correlation — treat it as a load-bearing constant.

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

`Surface` column distinguishes models that ride the bus (`bus`), models that are DB rows but never published (`db`), and models that are both with distinct envelope/row shapes (`bus+db`). DB-only models still need versioned Pydantic schemas (used by storage layer + migrations); they just don't define a NATS subject.

| Contract | Owner | File | Surface |
|---|---|---|---|
| `RawMessage` | EYENET | `contracts/raw_message.py` | bus+db |
| `Observation` (re-export) | BEHAVE-TEXT | imported | bus+db |
| `IdentityLabel` | EYENET | `contracts/identity.py` | bus+db |
| `EngagementAuthorization` | EYENET | `contracts/identity.py` | bus+db |
| `ProfileCandidate` | EYENET | `contracts/attribution.py` | bus |
| `ProfileCurrent` | EYENET | `contracts/attribution.py` | bus+db (DB row = `Profile`, MODELS §2.4) |
| `LinkageProposed` | EYENET | `contracts/attribution.py` | bus |
| `Linkage` | EYENET | `contracts/attribution.py` | db (MODELS §2.5) |
| `Persona` | EYENET | `contracts/attribution.py` | db (MODELS §2.6) |
| `Membership` | EYENET | `contracts/social_graph.py` | db (MODELS §2.2) |
| `InfrastructureArtifact` | EYENET | `contracts/infrastructure.py` | db (MODELS §2.7) |
| `ActorArtifact` | EYENET | `contracts/infrastructure.py` | db (MODELS §2.8) |
| `Attachment` | EYENET | `contracts/message.py` | db (MODELS §2.9) |
| `ActorAliasHistory` | EYENET | `contracts/actor.py` | db (MODELS §2.10) |
| `GroupSnapshot` | EYENET | `contracts/group.py` | db (MODELS §2.11) |
| `Case` | EYENET | `contracts/case.py` | db (MODELS §2.15) |
| `SystemUser` | EYENET | `contracts/system_user.py` | db (MODELS §2.17) |
| `AuditEvent` / `AuditLog` row | EYENET | `contracts/audit.py` | bus+db (hash-chained, MODELS §2.14) |
| `SystemLog` row | EYENET | `contracts/syslog.py` | db (MODELS §2.18) |
| `Bus` interface | EYENET | `contracts/bus.py` | — |
| `Storage` interface | EYENET | `contracts/storage.py` | — |
| `IdentityPool` interface | EYENET | `contracts/identity_pool.py` | — |
| `CollectorBase` interface | EYENET | `contracts/collector.py` | — |
| `SensorBase` interface | EYENET | `contracts/sensor.py` | — |

**`/contracts/` is the schema directory, not the bus directory.** The `Surface` column governs whether a NATS `SUBJECT` constant + envelope wrapper is generated for a given model. `Surface=db` models are SQLModel rows accompanied by a Pydantic schema for validation/migrations only — they MUST NOT export a `SUBJECT` symbol or `subject()` helper, and they are NEVER published to the bus. `Surface=bus+db` models export both: a wire envelope shape (subject-bearing) AND a persisted row shape, with shared identifiers but distinct schemas (see §4 of MODELS.md).

**Contract-test gate:** for every model with `Surface=db`, the contract suite asserts that no `SUBJECT` constant or `subject()` helper is exported from its module. For every model with `Surface=bus` or `bus+db`, it asserts that exactly one `SUBJECT` constant is exported and matches the taxonomy in §3. A future maintainer cannot accidentally publish `Persona` or `Case` to NATS — the build refuses.

### 4.3 Evidence handling — the rule

EYENET is operator-grade, not consumer-privacy-minimized. The rule is mechanical:

- **Bus envelopes carry hashes/aggregates only.** `MessageStore` holds bodies. Transport choice driven by fanout and BEHAVE-TEXT envelope shape — not a privacy fence.
- **`evidence_ref` is dereferenceable** by Engine, Linker, Graph, operator UI/CLI. Resolve it whenever context is needed.
- **Every dereference outside the producing Sensor emits `eyenet.audit.evidence_access`** carrying `service`, `instance_id`, `system_user_id` (if applicable), `evidence_ref`, `reason`. Audit, don't restrict.
- **Actor join keys are opaque hashes** (`actor:<sha256(source_kind||platform_userid)>`, see MODELS §0). Handle/display name live in the message store; freely retrievable.
- **Never on the bus, ever:** identity-pool secrets (session files, proxy creds), age/encryption keys. Disk-only, encrypted, per-collector.
- **Targeting/intent context** (`content.targeting_language`, `content.transactional_language`, `content.boasting_pattern`, ...) is a first-class observation namespace. Experimental caveat from BEHAVE-TEXT applies — weight skeptically.

---

## 5. Storage

### 5.1 Tiers

| Tier | Contents | Backend (v0) | Retention |
|---|---|---|---|
| **Hot** | Active corpora, open profiles, recent observations, graph state | SQLite + sqlite-vec | bound to `Case.state` (see below) |
| **Cold** | Closed-case messages, historical observations | Compressed NDJSON / Parquet on disk | configurable, default 1 year |
| **Archived** | Evidence-grade, encrypted (age) | Out-of-band volume | indefinite, manual access |

**Hot → cold trigger.** Hot-tier residency is bound to `Case.state` (MODELS §2.15). When ALL `Case` rows referencing an `actor_id` (via `Case.actor_ids`) have transitioned to `closed`, that actor's messages and observations become eligible for cold-tier migration after a configurable grace period (default 30 days from the latest `Case.closed_at`). Orphan data — actors/messages with no `Case` reference — stays hot until manually archived; we do NOT auto-evict on age alone, because an unreferenced actor may simply not have an investigation opened yet. Migration is **operator-triggered** via CLI; nothing auto-deletes. Reverse migration (cold → hot) is supported when a closed `Case` is reopened.

**Attachment binaries:** v0 default is **OFF** — `Attachment` rows (MODELS §2.9) capture metadata (mime, size, sha256, filename) but the binary is NOT downloaded or stored. Per-`Case` opt-in flips retention on; binaries then land at `<data_dir>/attachments/<sha256[:2]>/<sha256>` with `Attachment.storage_uri` pointing to that path. S3-compatible object storage is post-v0; the path-string field is forward-compatible.

### 5.2 Storage interface (abstract factory)

`Storage` interface with separate sub-interfaces:
- `MessageStore` — raw messages by `evidence_ref`.
- `CorpusStore` — append-only per-actor message history.
- `ObservationStore` — observations indexed by `(actor_id, primitive, ts)`.
- `ProfileStore` — current + historical profile states.
- `VectorIndex` — similarity search over hash/vector primitives (sqlite-vec for TF-IDF; flat SQL Hamming for simhashes until ~1M signatures).
- `GraphStore` — nodes + edges with typed relations.

v0 implementation: **all backed by SQLite** in separate database files, one per concern. Migration to Postgres + pgvector + Neo4j when scale forces it; the abstract factory pays for itself there.

**Cross-store join boundaries.** Multiple SQLite files = no cross-database SQL joins. The boundaries (and the application-side join code that crosses them) are:
- `MessageStore` ↔ `ObservationStore` — joined by `evidence_ref` in app code (Sensor, Engine read paths).
- `ObservationStore` ↔ `ProfileStore` — joined by `actor_id` in Engine.
- `ProfileStore` ↔ `GraphStore` — joined by `actor_id` in Linker / Graph upsert.
- `VectorIndex` keys are `(actor_id, primitive_name)` and dereference into `ObservationStore` for raw values.

All other "joins" are forbidden — if a query needs them, it's a sign two stores should be merged or a denormalized view added.

**`Linkage` table constraint.** Per MODELS §2.5, store the unordered pair as `(actor_a_id, actor_b_id)` with the invariant `actor_a_id < actor_b_id` (lexicographic on UUIDv7). Enforced at the DB layer with a CHECK constraint AND in the contract `__init__` validator. Insertion code MUST sort the pair before write; this prevents duplicate `(A,B)` / `(B,A)` linkage rows.

### 5.3 Per-actor corpus

Append-only. Each row: `(actor_id, ts, evidence_ref, message_length, language)`.

**Cursor model — per-primitive, not per-actor.** Sensors track progress in a `CorpusCursor` table (MODELS §2.16) with composite PK `(actor_id, primitive_name)` and fields `(last_processed_msg_ts, last_processed_msg_id)`. Different primitives have different windows (some run per-message, some over rolling N-message windows, some over time-bucketed slices) — they MUST NOT share a single ts cursor or fast primitives will skip messages slow primitives haven't seen. The pair `(ts, msg_id)` disambiguates same-timestamp messages and is the safe restart key.

---

## 6. Identity Pool & OPSEC

### 6.1 Pool design

- Pool config: `identities.toml` outside the repo (gitignored, age-encrypted at rest).
- Each entry: session file path, proxy/Tor circuit ID, device fingerprint hash, cooldown window, last-used timestamp.
- **Device fingerprint hash — canonical inputs.** `device_fingerprint = sha256(json.dumps(tuple, sort_keys=True))` over the source-specific tuple below. Two collector implementations MUST produce identical hashes for identical identities or OPSEC correlation breaks silently.
  - `telegram`: `(api_id: int, device_model: str, system_version: str, app_version: str, lang_code: str, system_lang_code: str)`
  - `matrix`: `(homeserver_url: str, device_id: str, user_agent: str)`
  - `irc`: `(server: str, nick: str, ident: str, realname: str, client_version: str)`
  - `discord`: `(client_build_number: int, user_agent: str, super_properties_hash: str)`
  - `forum` / HTTP-scrape: `(user_agent: str, accept_language: str, tls_fingerprint: str)`
  - Unknown source kinds MUST register their tuple shape in `contracts/collector.py` before merging a concrete collector.
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
- **Wire the predicate hook NOW.** A single `should_keep_trace(root_span, span_tree) -> bool` predicate lives in `eyenet.tracing.sampling` and is called by the OTLP exporter before write. v0 default: `return True`. Costs ~30 lines, zero behavior change. When tail-sampling lands, flipping the default is a one-file edit instead of retrofitting every span emitter and exporter wiring.

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

- Separate stream: `eyenet.audit.{service}` on the bus, persisted to the `AuditLog` table (MODELS §2.14) AND mirrored to an NDJSON file with `0600` permissions.
- Audit events: identity pool rotation, manual label application, profile override, archive/delete tier transitions, kill-switch, collector start/stop with which identity, evidence dereference, linkage confirm/reject, case open/close, system_user login / permission change.
- **Tamper-evidence:** every `AuditLog` row is hash-chained — `prev_hash = sha256(previous_row.self_hash)`, `self_hash = sha256(canonicalized_fields)`. Insertion / deletion / edit breaks the chain on a single forward walk. Cheap, append-only-friendly, no fancy crypto.
- **Retention:** never auto-pruned. AuditLog is evidence. Only operator-initiated archive transitions a row out of the hot tier, and the chain is preserved across tiers.
- Audit log is **the** source of truth for "what did an operator do, and when?"

### 9.4 Log routing

- stdout JSON → systemd-journald (or container runtime). Firehose tier — `debug`, `info`, per-message chatter.
- Audit stream → `AuditLog` table + dedicated NDJSON file, `0600` permissions.
- Curated operational log → `SystemLog` table (see §9.5).
- No logs to syslog; no logs to network sinks in v0.

### 9.5 Curated operational log (`SystemLog`)

The journald firehose is for grep + tail. It is NOT operator-queryable from inside the app and it bloats fast. Per MODELS §2.18, EYENET also persists a curated subset of structured events to a `SystemLog` SQLite table — designed for the operator UI/CLI's "show me what's wrong" view.

**What lands in `SystemLog`:**
- Every `warn` and `error` line.
- Lifecycle events on a curated allowlist: service start/stop, identity-pool state change, NATS reconnect, contract-version mismatch handled by fallback, kill-switch trigger.
- Notice-level events deemed operator-visible.

**What does NOT land in `SystemLog`:**
- `debug` and most `info` lines — journald only.
- Per-message processing chatter — covered by traces (§8).
- Audit events — written to `AuditLog` (no double-write).

**Allowlist mechanism:** event names are dotted, lowercase, stable. The allowlist lives in `contracts/syslog.py` as a typed enum/set. Emitting an event whose name is on the allowlist routes it to `SystemLog` *in addition to* journald. Off-allowlist events go to journald only.

**Indexes** (MODELS §2.18): `(service, level, at DESC)` for the operator log view; `(stack_hash, at DESC)` for "show me all instances of this error."

**Retention:** rows older than N days (default 90) move to cold tier per §5.1. `AuditLog` never auto-prunes.

---

## 10. Roadmap

### Milestone 0 — Contracts only (no service code) — ✅ DONE (2026-05-04)
- ✅ All `contracts/*.py` files written (under `eyenet/contracts/`; layout note: `/contracts/` at repo root in §4.1 became `eyenet/contracts/` to match the scaffolded package).
- ✅ Companion SQLModel tables under `eyenet/models/` (23 tables, shared `SQLModel.metadata`; per-store engine routing deferred to M1's storage layer).
- ✅ Contract test suite passing — `pytest -m contract` 46/46 green; default `-m "unit or contract"` 48/48 green.
- ✅ `decnet-behave-core` + `decnet-behave-text` wired as path-editable via `[tool.uv.sources]`. `Observation` re-exported, not redefined.
- ✅ Build-gate active: `test_surface_gate.py` refuses Surface=db modules that export `SUBJECT*` and Surface=bus modules that don't.
- ✅ Pinned constants under contract test: `compute_instance_id` (PLAN §2.1), `device_fingerprint` per-source tuples (PLAN §6.1), `Linkage` `actor_a_id < actor_b_id` invariant, EngagementAuthorization exactly-one-of discriminator, AuditLog hash-chain edit/insert/delete detection.
- ✅ This document accepted.

### Milestone 1 — Bus + skeleton services — ✅ DONE (2026-05-04)
- ✅ Two `Bus` impls: `NATSBus` (`eyenet/bus/nats.py`) over `nats-py` and `MemoryBus` (`eyenet/bus/memory.py`) for unit/integration tests. Subject matcher (`subjects.py`) handles `*` / `>` wildcards. `BusEnvelopePublisher` enforces `trace_context` on every publish and refuses unknown subjects (PLAN §3 taxonomy).
- ✅ `SQLiteStorage` aggregate (`eyenet/storage/sqlite.py`) — 8 per-store SQLite files (`messages.db`, `corpus.db`, `observations.db`, `profiles.db`, `vectors.db`, `graph.db`, `audit.db`, `syslog.db`) with WAL + FK pragmas. Cross-store FKs dropped per PLAN §5.2 — boundaries crossed in app code. AuditLog hash-chain enforced inside the write transaction; mirrored to `audit.ndjson` (mode `0600`).
- ✅ Telemetry (`eyenet/telemetry/`): OTel `init_telemetry`, W3C trace context extract/inject, structlog JSON renderer auto-populating `trace_id`/`span_id`, `should_keep_trace` predicate hook (PLAN §8.6, returns True), `AuditEmitter` for combined bus + persisted audit emit.
- ✅ `FileIdentityPool` (`eyenet/identity_pool/file.py`) — TOML reader, claim/release/freeze_all state machine, persisted across restarts. `device_fingerprint` per-source schemas pinned (PLAN §6.1).
- ✅ `ServiceBase` + `run_service` (`eyenet/service/`) — boot order, SIGTERM/SIGINT handlers, `service.start`/`service.stop` audit + syslog. Bus close is caller-owned so co-resident services share one bus.
- ✅ Five service skeletons: `TelegramCollectorStub` (synthetic envelope producer from JSONL fixture), `SensorSkeleton`, `EngineSkeleton`, `LinkerSkeleton`, `GraphSkeleton`. Each subscribes to its taxonomy entries and logs receipt; no domain logic yet.
- ✅ CLI commands (`eyenet/cli/main.py`): `collector-run`, `sensor-run`, `engine-run`, `linker-run`, `graph-run`, `panic`. `--memory-bus` flag for dev-loop convenience.
- ✅ Tests: 98 unit/contract green (`pytest -m "unit or contract"`), 2 integration green (multi-collector + full-fleet over `MemoryBus`), 1 e2e gated on `EYENET_E2E=1` (testcontainers NATS). Mypy strict clean, ruff clean.
- ✅ Live smoke: `eyenet engine-run --memory-bus` boots, emits chained `service.start`/`service.stop` audit, exits cleanly on SIGTERM.

### Milestone 2 — First Telegram collector + sensors — ✅ DONE (2026-05-11)
- One Telegram collector instance with one identity from the pool.
- Sensors implement stylometric primitives v0.2 (function_word_top50, character_ngram_simhash, distinctive_vocabulary_signature, MATTR).
- End-to-end: real Telegram channel → observations on bus → SQLite.

**Primitive → `Profile` slot mapping (Engine input contract for M3).** Engine work in M3 cannot start until this table is pinned, because `Profile` summary fields (MODELS §2.4) are populated *from* primitive observations and the recipes consume them downstream:

| Primitive (BEHAVE-TEXT name) | Namespace | Value kind | `Profile` slot |
|---|---|---|---|
| `function_word_distribution_top50` | `stylometric` | hash (simhash) | `stylometric_summary.function_word_simhash` |
| `character_ngram_simhash` | `stylometric` | hash (simhash) | `stylometric_summary.char_ngram_simhash` |
| `distinctive_vocabulary_signature` | `lexical` | array_str | `lexical_summary.distinctive_vocab` |
| `MATTR` (moving avg type-token ratio) | `lexical` | numeric | `lexical_summary.mattr` |

Each `Profile.*_summary` slot also stores `last_observation_id` and `derived_from_observation_count` for explainability (MODELS §2.4). New primitives added later append slots; they do NOT rename existing ones (recipe stability).

### Milestone 2.5 — Multi-collector validation
- Run two Telegram collectors with two distinct identities concurrently.
- Validate no cross-talk, no shared state, separate trace lineages, separate audit entries.

### Milestone 3 — Engine + profiles — ✅ DONE (2026-05-13)
- Profile recipes from `attribution-recipes.md` placeholders, starting with `lurker_or_observer` and `bot_or_automated_poster`.
- Profile current/candidate flow.
- Four new primitives: `message_length`, `message_length_variance_class`, `punctuation_style`, `typo_signature`, `conversation_initiation_rate`.
- Engine: per-observation slot mapping, debounced ProfileCurrent, recipe registry.
- Integration test: Collector+Sensor+Engine e2e on MemoryBus, two synthetic actors with known role signals.
- CLI: `eyenet engine` upgraded; `--fixture/--duration/--dump-profiles` smoke mode.

### Milestone 4 — Linker + graph — ✅ DONE (2026-05-22)
- ✅ Linker (`eyenet/linker/`): Comparator Protocol + REGISTRY (`comparators/_base.py`, `comparators/__init__.py`); two simhash comparators — `function_word_simhash_hamming` (default 8 bits) and `char_ngram_simhash_hamming` (default 10 bits). Both thresholds are **UNCALIBRATED** until M5 Rutify; markers in source point at the handoff. `hamming64(hex_a, hex_b)` in `_distance.py` is the shared distance primitive. The Linker drives the per-comparator VectorIndex upsert + nearest-neighbor probe, emits `attribution.linkage.proposed` per match, and audit-logs each proposal.
- ✅ Graph service (`eyenet/graph/graph.py`, 291 LOC): subscribes to `attribution.profile.current` (Actor node upsert) and `attribution.linkage.{proposed,suspected,confirmed,rejected}` (LinkedTo edge state machine). On confirm, calls `storage.personas.merge_actors` (union-find), upserts the Persona node + BelongsToPersona edges, and emits `attribution.persona.updated`. Replay-safe — every handler is idempotent.
- ✅ Query API (`eyenet/query_api/`): read-only FastAPI app, localhost-default with an `EYENET_QUERY_API_ALLOW_PUBLIC=1` gate against accidental public bind. Five GET endpoints: actor summary, actor neighbors (typed-edge filter), persona, linkages, graph/stats. No write endpoints — operator decisions stay CLI + audit-logged.
- ✅ Storage: `LinkageStore.transition()` enforces the PROPOSED → {SUSPECTED, CONFIRMED, REJECTED} state machine, `(actor_a_id < actor_b_id)` unordered-pair invariant per MODELS §2.5; `SQLitePersonaStore.merge_actors()` handles forward (`Persona.member_actor_ids`) + reverse (`PersonaMembership`) views; `GraphStore.upsert_node` / `upsert_edge` / `neighbors` / `edges_by_type` / `stats` cover the read & write surfaces. Open Question §11.1 resolved — SQLite-with-edges shipped.
- ✅ CLI: `eyenet linker`, `eyenet graph`, `eyenet graph-api` (`eyenet/cli/main.py:341-395`). All share `--data-dir`/`--nats-url`/`--memory-bus` flags with the M1 service runners. `eyenet panic` (global control subject) covers M4 services via `ServiceBase` inheritance.
- ✅ Tests: `369 unit/contract green` (`uv run pytest`), M4 integration tests on MemoryBus — `test_linker_e2e.py`, `test_m4_full_pipeline.py`, `test_query_api.py` — and the new `tests/e2e/test_m4_nats_pipeline.py` proving the full propose→confirm→persona walk over real NATS (gated on `EYENET_E2E=1`; either testcontainers `NatsContainer` or `EYENET_NATS_URL` override). Mypy strict clean. Ruff clean. Coverage 89.30%.
- ✅ Live smoke: `eyenet linker` + `eyenet graph` + `eyenet graph-api` co-resident against running `nats-server -js` on `nats://127.0.0.1:4222`. `GET /graph/stats` returns the zero-state JSON `{"actors":0,"personas":0,"linked_to_edges":0,"belongs_to_persona_edges":0}`. SIGTERM cleanly produces paired `service.start` / `service.stop` audit rows for both services with a single linear hash chain.
- ✅ Thresholds deliberately UNCALIBRATED; M5 Rutify grid is the next consumer.
- ✅ Multi-writer storage hardening: `engines.open_all()` holds a POSIX `flock` on `<data_dir>/.eyenet-init.lock` to serialize first-time schema init across processes (`eyenet/storage/engines.py`). `SQLiteAuditStore.append()` opens a raw DBAPI connection and issues an explicit `BEGIN IMMEDIATE` so concurrent audit writes from co-resident services serialize at the SQLite RESERVED-lock layer (`eyenet/storage/audit.py`). Proven by `tests/unit/storage/test_init_concurrency.py`, `tests/unit/storage/test_audit_concurrency.py`, and `tests/e2e/test_concurrent_boot.py`.

**Carries forward to M5:**
- Calibrate `function_word_simhash_hamming` and `char_ngram_simhash_hamming` thresholds against Rutify, replace `UNCALIBRATED` markers in `comparators/_base.py`.

### Milestone 5 — Calibration on Rutify corpus
- Calibration test suite green.
- First written attribution recipes for EYENET (replacing BEHAVE-TEXT placeholder).

### Milestone 6 — Second source
- A second `CollectorBase` implementation (Matrix or Forum). The point is not the source — the point is to *prove the abstract factory holds*.

---

## 11. Open Questions

1. ~~**Graph backend final choice:**~~ **Resolved (M4, 2026-05-22).** SQLite-with-edges shipped via `eyenet/storage/graph.py` + `eyenet/models/graph.py` — `GraphStore` exposes `upsert_node`, `upsert_edge`, `neighbors`, `edges_by_type`, `stats`. Typed `GraphNodeType` (`Actor`, `Persona`) and `GraphEdgeType` (`LinkedTo`, `BelongsToPersona`) drive the relation set. Zero-ops, embedded, no external server. Revisit only if scale forces a move to Neo4j or ArangoDB — the `GraphStore` interface is the swap point.
2. ~~**Profile-state representation:**~~ **Resolved (M3, 2026-05-13).** Snapshot-per-update with monotonic `version` won. `ProfileTable` (`eyenet/models/profile.py:19-45`) writes a new row per Engine update with `version += 1`; a partial unique index (`ix_profile_one_current_per_actor`, `sqlite_where=is_current=1`) floats `is_current=True` to the newest row and forbids duplicates. Full history is preserved as immutable per-version rows — audit-friendly without a separate event log. `ProfileStore.history(actor_id)` (`eyenet/storage/profiles.py:50`) is `WHERE actor_id=? ORDER BY version asc`. Best of both worlds: snapshot ergonomics, event-sourced retention.
3. ~~**Cross-platform actor ID:**~~ **Resolved.** Per-platform `actor_key` (`actor:<sha256(source_kind||platform_userid)>`, MODELS §0) stays the stable join key. Cross-platform identity is **not** a derived `actor_key` — it is a separate `Persona` / `ActorCluster` entity (MODELS §2.6) constructed from confirmed `Linkage` rows (MODELS §2.5). `Persona.member_actor_ids` is the denormalized forward view (cheap reads); `PersonaMembership` (MODELS §2.6a) is the indexed reverse view (`actor_id → persona_id` lookup). Both are rebuildable from the linkage graph. Engine, Linker, and Graph never collapse two per-platform actor_keys into one; they emit/confirm linkages and let `Persona` carry the cluster.
4. **Collector Supervisor:** deferred — manual launch is fine until the fleet exceeds ~3 collectors. Revisit only if real deployments outgrow that.
5. **BEHAVE-SHELL fusion:** if a Telegram actor is also observed in a PTY (BEHAVE-SHELL), can the engine fuse both substrates? Out of scope for v0; flagged for v1.

---

## 12. Non-Goals (v0)

- No automated engagement with actors.
- No active deception / honeypot behavior.
- No automated reporting to platforms.
- No web UI (CLI + graph query API only).
- ~~No multi-tenant operator separation.~~ **Revised (2026-05-04):** multi-user IS in scope as of MODELS.md §2.17 (`SystemUser`). v0 default is single-user, but the model and permission system are designed for N operators from the start. Multi-tenant *isolation* (separate data realms per tenant) remains a non-goal.
