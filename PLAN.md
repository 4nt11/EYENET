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

### Milestone 5 — Calibration on Rutify corpus — ✅ DONE (2026-05-23)
- ✅ **Calibration package** (`eyenet/calibration/`, 8 modules + CLI subapp): `corpus.py` (JSONL ingest + chronological split-halves), `interaction.py` (per-actor stats), `simhash_grid.py` (within/cross Hamming + Mann-Whitney AUC + F1/precision-floor sweep), `labels.py` (TOML schema + corpus-sha256 pinning), `recipes_grid.py` (recipe threshold search with AND-of-axes groups OR-combined), `artifact.py` (hash-pinned `CalibrationArtifact` dataclass + JSON I/O), `cli.py` (typer subapp).
- ✅ **Phase 0.5 — detected language surfaced**: `function_word_distribution_top50` already encodes the detected language in its `Observation.source` suffix (`...#es` / `...#en`); slot_mapper now parses it into `Profile.stylometric_summary.function_word_simhash.language`. char_ngram inherits from there. Zero DB migration (JSON column). New whitelist `_LANGUAGE_SUFFIX_PRIMITIVES` keeps the parse opt-in.
- ✅ **Phase 0.6 — per-language threshold schema**: both simhash comparators expose `slot_language(envelope) -> str | None`; `LinkerThresholds` gains `function_word_simhash_hamming_per_lang: dict[str, int | None]` (None = "disabled for this language"). `for_comparator(name, language)` returns `int | None`; Linker skips the comparator entirely when None.
- ✅ **Simhash grid against Rutify (Spanish)**: 73 actors qualifying at `min_messages=50`, 59 firing function_word, 46 firing char_ngram. AUC=0.5546 (function_word) and 0.6776 (char_ngram). Maximum achievable precision: 0.118 / 0.333. **Operator decision (2026-05-22): disable simhash linker for Spanish entirely.** `LinkerThresholds` default factory ships `{"es": None}` for both per-lang dicts. Long-term fix is `minhash-with-shingles` in BEHAVE-TEXT 0.0.2.
- ✅ **Recipe grid against 74 labeled actors** (73 simhash-qualifying + SangMata_beta_bot, the one confirmed sub-threshold bot):
  - `lurker_or_observer`: Pattern A (`init_rate <= 0.20`) shipped — P=1.000 R=0.400 on labeled set (catches 2 of 5 lurkers — the passive-responder class). Pattern B (`msg_per_day <= 2.0 AND span >= 7d`) calibrated in M5; wired to live deployment in M5.5 (lifts recall to 1.000 on the labeled set).
  - `bot_or_automated_poster`: operator-locked axes `init_rate >= 0.95 AND message_length_variance_class == "tight"` — P=1.000 R=1.000 against SangMata. inter_msg_cv dropped (event-driven bots fail clockwork gates); MATTR held as future tertiary axis (SangMata=0.49 vs human cohort min=0.82).
  - `chatty_member` (NEW): `msg_count >= 195` — P=1.000 R=0.955 calibrated in M5; deployment-unblocked in M5.5 by the `meta.total_messages` primitive populating `temporal_summary.message_count`.
- ✅ **`UNCALIBRATED_*` markers removed**: all recipe modules now ship `reasoning["calibrated"] = True` with `calibration_corpus = "rutify-full-2026-05-02"`. `grep -rn UNCALIBRATED eyenet/engine/recipes/ eyenet/linker/comparators/` returns zero hits.
- ✅ **Artifact**: `tests/fixtures/calibration/rutify_calibration_baseline.json` (4.8KB, self-hash `86b4e73a…`). Carries corpus sha256, eyenet + behave-text versions, full simhash AUC + sweep + recipe confusion matrices. No message bodies, no usernames — safe to commit alongside the gitignored corpus. Round-tripped via strict-typed `_from_dict` helpers (no `Any`).
- ✅ **Labels** (`rutify_labels.toml`, committed): 74 hand-labeled actors. `labeler = "claude-opus-4-7-via-anti"` per operator policy. Counts: 22 chatty_member / 46 normal / 5 lurker / 1 bot / 0 unknown.
- ✅ **Calibration test suite**: 16 tests under `tests/calibration/` (3 stub tests rewritten + 11 new). Covers per-recipe P/R floors, code-vs-artifact threshold consistency, simhash AUC regression budget (5% drop = fail), artifact self-hash integrity, config-vs-baseline disable mirror. `pytest -m calibration` green.
- ✅ **CLI**: `eyenet calibrate {run, label-helper, report, diff}` wired via typer subapp. `report` smoke-tested against the committed baseline.
- ✅ **Quality gates**: 453 default tests + 16 calibration tests green. `mypy --strict eyenet/` clean across 128 files. `ruff check eyenet/ tests/` clean. CSV/TOML/JSON artifacts committed.

**Carries forward to M6:**
- Implement `LLM-Confirmer` service (subscribes to `attribution.linkage.proposed`, samples evidence_refs, asks an LLM "same author?", emits `attribution.linkage.{confirmed,rejected}`). Becomes the de-facto linker for Spanish until BEHAVE-TEXT minhash-with-shingles lands.
- Re-enable simhash linker for Spanish when BEHAVE-TEXT ships `minhash-with-shingles`.

### Milestone 5.5 — Wire BEHAVE-TEXT 0.1.2 meta.* primitives — ✅ DONE (2026-05-23)
- ✅ **Eight new sensor primitives** under `eyenet/sensor/primitives/meta_*.py` — `total_messages`, `corpus_span_days`, `msg_per_day`, `active_days`, `activity_density`, `first_seen_ts`, `last_seen_ts`, `fingerprint_confidence`. All share a single corpus-stats kernel (`_meta_kernel.py`) that derives every field from one pass over per-actor timestamps. `fingerprint_confidence` cutoffs are EXTRACTOR-DEFINED per the BEHAVE-TEXT 0.1.2 spec; the heuristic ships pinned via source-label suffix `#confidence-v1`. Edge cases (empty corpus, single-day actor) suppress the Observation per the spec contract.
- ✅ **PrimitiveSpec extension**: new `requires_full_corpus: bool` flag — when set, `StylometricSensor._compute_primitive` passes epoch sentinels to `iter_since`, fetching the actor's full history instead of the since-cursor delta. Bodies fetch is also skipped (meta primitives are timestamp-only). Cursors still advance for bookkeeping uniformity.
- ✅ **Slot-mapper wiring**: eight `_SLOT_MAP` entries routing `meta.*` → `temporal_summary.*`. Slot key for `meta.total_messages` is `message_count` (not `total_messages`) to match `chatty_member.REQUIRED_SLOTS` verbatim — recipe never had to be edited.
- ✅ **`lurker_or_observer` Pattern B deployed**: second AxisGroup (`msg_per_day <= 2.0 AND corpus_span_days >= 7.0`) OR-combined with Pattern A. Recipe `REQUIRED_SLOTS = ()` (empty) because the OR-combinator must run when EITHER pattern's slots are populated — the recipe body has its own per-pattern guards. Labeled-set recall lifts from 0.40 → 1.000 (P stays 1.000).
- ✅ **`chatty_member` deployed**: deployment-blocked banner removed; threshold `msg_count >= 195` now fires on actors whose `meta.total_messages` populates `temporal_summary.message_count`.
- ✅ **Tests**: 18 new unit tests for the kernel + 8 primitives + cross-cutting cases; 8 new parametrized slot_mapper cases; 8 new Pattern B / both-patterns / no-data lurker cases; 1 new calibration regression case asserting Pattern B's msg_per_day + corpus_span_days axes match the artifact. Total: 487 default + 17 calibration green. `mypy --strict eyenet/` clean (137 source files). `ruff check` clean.
- ✅ **Live smoke**: `eyenet calibrate run` on the Rutify corpus reproduces the M5 P/R/F1 figures exactly across all three recipes (lurker 5/0/69/0 P=R=1.000, bot 1/0/73/0 P=R=1.000, chatty 21/0/52/1 P=1.000 R=0.955). Artifact `self_hash` differs from the committed baseline only because of metadata drift that pre-dates M5.5 (`behave_text_version` bumped 0.1.1 → 0.1.3 in the operator's environment, `corpus_id` filename changed). Calibration math is identical.

**Carries forward to M6:**
- Re-issue `rutify_calibration_baseline.json` against BEHAVE-TEXT 0.1.3 + the new `corpus_id` if/when the operator wants the committed baseline back in self-hash agreement. The M5.5 wiring did not introduce the drift; the baseline simply pre-dates it.

### Milestone 6 — Locale-aware primitives: `lexical.dialect_region` — ✅ DONE (2026-05-23)

First of four language-agnostic, locale-aware primitives. BCP-47 `xx-YY` is the universal output; Spanish is the first calibrated language, not the design scope. Adding a second language (English, Portuguese, ...) post-M6 is a matter of registering its marker vocab — no primitive contract changes.

- ✅ **INGEOTEC vocabulary corpus committed via git-lfs** at `data/ingeotec/voc/*.tsv.gz` (27 files × ~2-13MB, regional-spanish-models v1). `.gitattributes` configured (`filter=lfs diff=lfs merge=lfs -text`); LFS hooks merged into `.githooks/pre-push` and new `post-checkout` / `post-commit` / `post-merge`. `data/` gitignore restructured to `data/*` + `!data/ingeotec/` so the corpus tracks while other data subdirs (storage, attachments) stay excluded.
- ✅ **Offline marker builder** (`scripts/build_regional_markers.py`, ~270 LOC): reads INGEOTEC `<CC>.tsv.gz` files, computes exclusivity = `freq[region][tok] / sum_all_regions_freq[tok]`, applies a comprehensive blocklist of TIME-DECAYING proper nouns (politicians, parties, sports clubs, cities, media outlets, Twitter handles), structural acronym filter (length-3 with ≤1 vowel rejected unless in `_DIALECTAL_3CHAR_WHITELIST`), and emits top-N per region by `exclusivity × log(1+ndocs)`. Default thresholds: `excl ≥ 0.70`, `min_ndocs ≥ 5000`, `top_n = 80`.
- ✅ **Generated markers** (`eyenet/sensor/primitives/_regional_markers.py`): 14 BCP-47 regions, 569 total markers. Strong coverage on es-AR (boludo, che, posta, laburo, quilombo, vos, sos, tenes, …), es-CL (weon, altiro, aweonao, callampa, fome, cabros, conchetumare, …), es-MX (chido, chingo, chingon, culero, neta, chinga, …), es-VE (chamo, marico, arrecho, bachaqueo, …), es-ES (cojones, gilipollas, flipando, chaval, ostia, mola, guay, …), es-CO (chimba, bacano, gonorrea, hijueputa, gamin, dizque, …), es-PE (causa, pata, pituco, …). Sparse coverage on es-BO, es-CU, es-PR (low INGEOTEC sample size; revisit when richer corpora land).
- ✅ **Primitive module** (`eyenet/sensor/primitives/dialect_region.py`, ~180 LOC): `requires_full_corpus=True`, MIN_MESSAGES=10, MIN_HIT_RATE=0.001, CONFIDENCE_MARGIN=1.8. Language gate via inline function-word overlap vote (es vs en, ~16 anchors each) — wrong language returns `None`. Below-confidence emits `Observation(value="unknown")` per BEHAVE-TEXT 0.1.x spec so downstream can distinguish "undetected" from "not extracted". Source label `eyenet/sensor/primitives/dialect-region:v0.1#dialect-markers-v1`.
- ✅ **Slot wiring** (`eyenet/engine/slot_mapper.py`): `"lexical.dialect_region": ("lexical_summary", "dialect_region")`. NOT in `_LANGUAGE_SUFFIX_PRIMITIVES` (it IS the language/region detector; redundant).
- ✅ **Tests** (`tests/unit/sensor/primitives/test_dialect_region.py`, 19 cases): registry contract, requires_full_corpus, language gate (English → None), ambiguous Spanish → unknown, region detection (AR/CL/MX/VE/ES), tied-region margin gate, observation source/confidence shape, slot mapper wiring, marker-set integrity (BCP-47 format, non-empty, single-token).
- ✅ **Quality gates**: 506 unit+contract tests green (was 487, +19 dialect_region). `mypy --strict eyenet/` clean across 139 source files. `ruff check eyenet/ tests/ scripts/` clean.
- ✅ **Live smoke**: `python3 scripts/build_regional_markers.py` reproduces the committed `_regional_markers.py` byte-for-byte from `data/ingeotec/voc/*.tsv.gz`.

**Carries forward to M6.5:**
- Iterative blocklist tuning. The current blocklist catches the bulk of political/sports/city noise but new proper nouns will surface as the operator audits attribution traces. Add to `_NOISE_BLOCKLIST` and re-run the builder.
- A small residual of names (~5%) still passes the filter; harmless for attribution but worth a periodic sweep.

### Milestone 6.5 — Locale-aware primitives: spaCy trio — ✅ DONE (2026-05-23)

- ✅ **Three primitives** sharing a single spaCy tagger pass via `eyenet/sensor/primitives/_locale_morph_kernel.py`:
  - `stylometric.pos_ngram_signature` — 64-bit simhash over UPOS bigram counts. Source label declares tagger + n: `#spacy-es_core_news_sm-bi`. MIN_TOKENS=200.
  - `lexical.evaluative_morphology_density` — sum(eval-bucket hits) / NOUN+ADJ count. Buckets: diminutive, augmentative, pejorative, intensive. Range clamped [0, 1] per BEHAVE-TEXT spec. MIN_TARGET_TOKENS=50.
  - `lexical.optional_grammar_signature` — 64-bit simhash over choice-point bucket counts: compound_past, subjunctive, clitic_le/la/lo, relative_que/cual/quien. MIN_TOKENS=200.
- ✅ **spaCy is a CORE dependency** (`pyproject.toml`), not optional. Operator decision 2026-05-23: EYENET ships small-operator CTI; operators accept the storage cost in exchange for working software out of the box. The `es_core_news_sm` model (~13MB) is **auto-fetched on first run** by `_load_nlp()` via `spacy.cli.download`, with a structlog audit event `event=spacy.model_downloaded`. spaCy loads with `parser` and `ner` disabled but `lemmatizer + attribute_ruler` enabled — the optional-grammar rule pack reads `token.lemma_` for `haber`.
- ✅ **`LocaleRuleset` protocol** + registry (`eyenet/sensor/primitives/_locale_rules/__init__.py`). Spanish ruleset (`_locale_rules/es.py`) ships first; future English/Portuguese register a `RULESET` constant + a `RULESETS[code]` entry, no kernel changes. Surface-form rules for evaluative morphology (sm lemmatizer preserves diminutives, so lemma-based detection is impossible); `token.morph.get("Mood", [])` for subjunctive (immune to the sm lemmatizer's irregular-verb mangling, e.g. `fuera → fuerir`). Blocklist for lexicalized "-ito" / "-azo" / "-ico" surface forms (`bonito`, `escrito`, `politico`, …).
- ✅ **Shared kernel** (`_locale_morph_kernel.py`): single `nlp.pipe(batch_size=64)` pass yields `MorphAnalysis` (pos_bigrams Counter + evaluative_counts + optional_grammar_counts + token totals + window). All three primitives consume the same analysis.
- ✅ **Language gate consolidated**: `dialect_region` (M6) and the M6.5 trio now share `_locale_rules/_language_gate.py` (`is_spanish` + `detect_language` returning BCP-47 code). Anchor sets unchanged from M6.
- ✅ **Slot wiring** (`eyenet/engine/slot_mapper.py`): three new `_SLOT_MAP` entries (`stylometric_summary.pos_ngram_signature`, `lexical_summary.evaluative_morphology_density`, `lexical_summary.optional_grammar_signature`). Both simhash primitives added to `_LANGUAGE_SUFFIX_PRIMITIVES` — they encode `#<lang>` themselves; the density primitive stays off (numeric, no per-language threshold branch).
- ✅ **Two new linker comparators** (`pos_ngram_simhash_hamming`, `optional_grammar_simhash_hamming`) registered in `REGISTRY`. `LinkerThresholds` ships **calibrated defaults for Spanish**: `pos_ngram_simhash_hamming_per_lang = {"es": 10}` and `optional_grammar_simhash_hamming_per_lang = {"es": 12}`. Calibration logic in `eyenet/calibration/artifact.py` scopes the M5 ES-blanket-disable to the M5 primitives only — M6.5 simhashes are exempt.
- ✅ **Calibration grid extended** (`eyenet/calibration/simhash_grid.py`): default primitive tuple now includes `pos_ngram_signature` + `optional_grammar_signature`; both detect their own language via the source-label suffix path (`_SELF_LANG_PRIMITIVES`). The committed `rutify_calibration_baseline.json` pre-dates M6.5; the next `eyenet calibrate run` against the corpus will emit grid entries for the new primitives and the M6.5 calibration regression tests will lift to AUC budget assertions.
- ✅ **Tests**: 52 new unit tests (`test_locale_morph_kernel.py` 22, `test_pos_ngram_signature.py` 11, `test_evaluative_morphology_density.py` 10, `test_optional_grammar_signature.py` 9) + 4 new calibration regression tests (`test_simhash_thresholds.py`). Total: 558 default + 21 calibration green. Coverage 85.48% (above gate).
- ✅ **Quality gates**: `pytest -m "unit or contract"` 558 green; `pytest -m calibration` 21 green; `mypy --strict eyenet/` clean across 148 source files; `ruff check eyenet/ tests/ scripts/` clean.
- ✅ **Live smoke**: in-process end-to-end (Spanish chat paragraph → all three primitives emit valid Observations with expected source-label suffixes). Auto-fetch of `es_core_news_sm` verified in a fresh venv.

**Fixes pass — round 2 (2026-05-23, same day):** honest review found a deeper set of gaps. Closed:
- ✅ **Production correctness bug, not just a perf issue.** Pre-fix `_compute_primitive` skipped body fetches for ALL `requires_full_corpus=True` primitives (gated on `if not spec.requires_full_corpus`), which silently broke the M6.5 trio end-to-end through the sensor — they got `bodies={}` and returned None every time. Fix: added `requires_bodies: bool = True` to `PrimitiveSpec`; meta.* explicitly set `requires_bodies=False`; the trio inherits the default True. Now they actually run.
- ✅ **Sensor-side full-corpus + bodies memo.** `_run_primitives` lazily fetches the full corpus + body batch once per actor dispatch and reuses them across the 11 `requires_full_corpus=True` primitives (8 meta + 3 trio). Net savings per actor per dispatch: ~10 fewer SQLite reads and ~10 fewer MessageStore round-trips.
- ✅ **Kernel cache key tightened.** Now includes a bodies fingerprint — defends against the "same evidence_refs, different content" stale-result class of bugs that tests had been masking via UUID-prefixed refs.
- ✅ **`_KernelStats` dataclass** replaces the `_NLP_PIPE_CALLS` module global. Tests read `kernel._stats.pipe_calls` / `cache_hits` / `cache_misses`. The leading underscore signals test-visible-not-API; the additional counters make future debugging cheaper.
- ✅ **Sensor-integration tests prove the properties end-to-end.** `tests/integration/test_stylometric_kernel_memo.py` drives the real sensor dispatch loop with the synthetic_m2 fixture and asserts (a) `_stats.pipe_calls <= msg_count` — the kernel runs at most once per envelope across the trio, and (b) `iter_since` is called far less than `msg_count × 11` — the storage memo works.
- ✅ **CI bootstrap.** `tests/conftest.py` session-scoped fixture fails-fast with a clear remediation message if `es_core_news_sm` isn't installed. `scripts/install_models.py` is the documented provisioning entry point for CI runners. Production still auto-fetches on first run; CI gets the explicit path.
- ✅ **pytest-benchmark perf floor.** `tests/unit/sensor/primitives/test_locale_morph_kernel_benchmark.py` (opt-in via `pytest -m benchmark`) asserts mean kernel time over 200 messages is under 500ms. Local baseline ~190ms; budget catches >2.5× regressions.

Test count: 566 unit/contract (+1 cache-miss test from round 1's 565) + 18 integration (+2 new from this round) + 21 calibration. `mypy --strict` clean, `ruff` clean, coverage 85.43% above the 85% gate. E2E suite (`EYENET_E2E=1`) green: 3/3 against real NATS via testcontainers.

**Fixes pass — round 1 (2026-05-23):** earlier honest post-ship review surfaced five gaps that closed in the previous round:
- ✅ **Kernel is now genuinely single-pass per actor.** Added a module-level single-slot memo to `compute_morph_analysis()` keyed on `(language, tuple(evidence_refs))` — the sensor's per-actor dispatch rebuilds the `corpus` list per primitive, so `id()`-based memoization wouldn't hit. Across the three M6.5 primitive calls for one actor, spaCy now runs **once**, not three times. Verified by `_NLP_PIPE_CALLS == 1` after three back-to-back primitive calls; wallclock for the trio dropped from ~3× kernel cost to ~10ms total in the smoke.
- ✅ **Auto-fetch branch is exercised by a test.** `test_load_nlp_auto_downloads_on_missing_model` monkeypatches `spacy.load` to raise `OSError` on the first call, intercepts `_spacy_download`, and asserts the retry path fires exactly once. The OSError → download → retry contract is no longer theoretical.
- ✅ **`evidence_ref` falls back to the last in-bodies ref.** New `evidence_ref_for(corpus, bodies)` helper in the kernel walks the corpus in reverse and returns the most recent ref the kernel actually processed (one that's in `bodies`). All three primitives use it instead of `corpus[-1][2]`. Three new unit tests cover the trailing-missing-body case + the empty-overlap case.
- ✅ **`_reset_for_tests` properly exported**; companion `_reset_cache_for_tests` added for cheap between-test isolation (drops memo only, keeps the loaded spaCy model — full `_reset_for_tests` would multiply test-suite runtime by orders of magnitude). Conftest at `tests/unit/sensor/primitives/conftest.py` autouses the cache-only reset.
- ✅ **Gate divergence documented.** `_language_gate.py` module docstring now explains that `is_spanish` (loose, tie → True, used by M6 `dialect_region`) and `detect_language` (strict, ≥2 anchor hits required, used by the M6.5 trio) intentionally have different thresholds. The next reader won't "fix" the apparent inconsistency.
- Test count: 565 unit/contract (was 558, +7 fixes-pass) + 21 calibration; coverage 85.66% (up slightly); `mypy --strict` + `ruff check` clean.

**Calibration completion (2026-05-23, same day):** the Rutify re-run landed. Operator decision: **both new simhashes DISABLED for Spanish**, mirroring the M5 outcome on the existing pair:

| Primitive | AUC | Max precision (any t) | Operator action |
|---|---|---|---|
| `function_word_distribution_top50` | 0.5546 | 0.118 | M5 disable (unchanged) |
| `character_ngram_simhash` | 0.6776 | 0.333 | M5 disable (unchanged) |
| `pos_ngram_signature` | **0.6108** | 0.200 | **M6.5 disable (new)** |
| `optional_grammar_signature` | **0.6319** | 0.080 | **M6.5 disable (new)** |

Neither M6.5 simhash cleared the `precision_floor:0.70` strategy at any threshold — same structural ceiling as the M5 simhashes on short Spanish chat. Code changes:
- `LinkerThresholds.pos_ngram_simhash_hamming_per_lang = {"es": None}`
- `LinkerThresholds.optional_grammar_simhash_hamming_per_lang = {"es": None}`
- Artifact policy `_ES_DISABLED_PRIMITIVES` now includes all four ES-failing simhashes.
- `tests/fixtures/calibration/rutify_calibration_baseline.json` refreshed (`self_hash=d4aa2e26…`, `corpus_id=rutify-full-2026-05-02`, `corpus_sha256=bc0aab18…`); records `enabled=False, chosen_threshold=None` for all four ES slices.
- Calibration regression tests lifted from wiring-only to **AUC budget** (5% drop floors: 0.580 pos_ngram, 0.600 optional_grammar) + config-mirror + policy-set membership.
- Three calibrated recipes (`lurker_or_observer`, `bot_or_automated_poster`, `chatty_member`) re-validated — same P/R/F1 as M5.5 to four decimals.

Final gates: 566 unit/contract + 25 calibration + 18 integration + 3 E2E (real NATS) green. `mypy --strict` clean (148 files). `ruff` clean. Coverage 85.43%.

**Carries forward (still):**
- Re-enable simhashes for Spanish when BEHAVE-TEXT 0.0.2 ships minhash-with-shingles and/or when the LLM-Confirmer service lands. The disable list in `eyenet/calibration/artifact.py::_ES_DISABLED_PRIMITIVES` is the swap point.
- Wire `evaluative_morphology_density` as a `recipes_grid` axis when a recipe wants it. The slot is populated; the recipe consumer doesn't exist yet. Adding the axis requires computing the primitive during calibration in `interaction.py` and adding a new `ActorStats` column — real work, defer until a recipe needs it.
- Add an English ruleset (`_locale_rules/en.py`) when an English-language corpus lands. The kernel and slot wiring need zero changes — register `RULESET` + a `RULESETS["en"]` entry.

### Milestone 7 — Second source: Matrix — ✅ DONE (2026-05-23)

The point of M7 is to *prove the abstract factory holds*. Matrix beats Forum/IRC/RSS as the second source because matrix-nio is async-callback-driven like Telethon but the room/event model, auth (access_token vs MTProto session), and ID shapes (`@user:server` / `!room:server` / `$event_id`) are all materially different — making the "factory survives a wildly different SDK" claim much stronger.

- ✅ **matrix-nio>=0.24 added as a CORE dep** (`pyproject.toml`). No `[e2e]` extra — unencrypted rooms only in v0 (E2EE would add `libolm` C compile + per-identity key cache; deferred). `mypy.overrides` extended with `nio.*`. `coverage.omit` extended with `eyenet/collectors/matrix/real.py` (live-network code path).
- ✅ **`IdentityFileEntry` extended** (`eyenet/identity_pool/loader.py`) with `matrix_homeserver_url`, `matrix_user_id`, `matrix_access_token`, `matrix_device_id`, `matrix_monitor_rooms`. All optional — Telegram-only TOMLs round-trip unchanged. New helper `_uses_session_file(SourceKind) -> bool` scopes the on-disk session-file precheck to Telegram only; Matrix carries auth in the TOML so the existing loader's session_path existence check is now per-source instead of all-or-nothing.
- ✅ **`MatrixCollectorStub`** (`eyenet/collectors/matrix/stub.py`, ~95 LOC) mirrors `TelegramCollectorStub` line-for-line with `SourceKind.MATRIX`, `evidence_ref` prefix `matrix:<room_id>:<event_id>`, and the same JSONL replay shape.
- ✅ **`MatrixCollector`** (`eyenet/collectors/matrix/real.py`, ~320 LOC):
  - `AsyncClient(homeserver, user_id, device_id=...)` + pre-provisioned `access_token` — no login round-trip at start.
  - Room aliases (`#alias:server`) resolved to canonical `!room_id:server` via `client.room_resolve_alias`. `!`-prefixed entries pass through. Unknown forms warn and drop.
  - `add_event_callback(self._on_message, RoomMessageText)` — text events only for M7. `m.image` / `m.file` and other event kinds ignored at the callback level. Encrypted-room `MegolmEvent`s are silently dropped (not subscribed).
  - Self-echoes (sender == own user_id) dropped at ingest.
  - `actor_key = "actor:" + sha256("matrix||<user_id>")`. `evidence_ref = "matrix:<room_id>:<event_id>"`. `GroupKind.MATRIX_ROOM` on every monitored room.
  - **OPSEC: `set_presence="offline"` hard-coded on every `sync_forever` call. Matrix has no separate "invisible" presence; "offline" IS invisible. No operator knob — the constant `_PRESENCE_OFFLINE` is the only allowed value.**
- ✅ **CLI** (`eyenet/cli/main.py`) — `--type` extended to `{telegram-stub, telegram, matrix-stub, matrix}`. The legacy `stub` value is kept as a deprecated alias that emits a stderr warning + maps to `telegram-stub`. Session-file precheck now gated on `collector == "telegram"` only.
- ✅ **Backfill** via `/messages` pagination — opt-in with `--backfill`. Refuses if `matrix_monitor_rooms` is empty (would otherwise scrape every joined room — sanity stop). One-shot `sync` populates per-room `prev_batch` tokens; the collector then pages backwards in chunks of 100, ingesting text events via the same `_ingest_event` path as live sync. Default per-room limit 1000; configurable via `MatrixCollector(backfill_limit=...)`. Runs in parallel with `sync_forever`; MessageStore's unique-`evidence_ref` constraint deduplicates the overlap. Added 2026-05-23 same day as M7 in response to live-smoke feedback.
- ✅ **Deferred from Telegram parity (called out, not silent)**: attachments (text-only — `has_attachment=False` always), reply/relation parsing (`m.relates_to` deferred — `reply_to_platform_msgid` always None), E2EE.
- ✅ **Tests**: 15 new unit tests under `tests/unit/collectors/matrix/` (contract smoke, identity TOML round-trip, stub envelope shape, real-collector with a fake `AsyncClient` exercising on_subscribe, callback wiring, alias resolution, ingest, self-echo drop, presence=offline assertion). 1 new integration test `tests/integration/test_two_sources_one_sensor.py` — the M7 proof: Telegram + Matrix stubs on a single MemoryBus + sensor, asserts 6 envelopes (3+3), per-source subject partitioning, evidence_ref prefix matching, audit-row isolation across `collector.telegram` and `collector.matrix`. New fixture `tests/fixtures/corpora/synthetic_matrix.jsonl`.
- ✅ **Quality gates**: `pytest -m "unit or contract"` 581 green; `pytest -m integration` 19 green (was 18, +1 two-sources); `pytest -m calibration` 25 green. Coverage 86.25% (above 85% gate). `mypy --strict eyenet/` clean across 151 source files. `ruff check eyenet/ tests/ scripts/` clean.
- ✅ **Live smoke**: `eyenet collector --identity alpha_mx --type matrix-stub --fixture tests/fixtures/corpora/synthetic_matrix.jsonl --memory-bus` boots, emits hash-chained `service.start`/`service.stop` audit rows under `collector.matrix` with the contract-pinned `instance_id` (`4ba08aaf` for identity `alpha_mx`), exits cleanly on SIGTERM.

**Carries forward (defer until an operator asks):**
- E2EE rooms — wire matrix-nio `[e2e]` (libolm) and a per-identity key cache when an operator needs to monitor an encrypted room.
- Attachments — `m.image` / `m.file` events into `AttachmentTable` rows.
- Reply graph — `m.relates_to` parsing into `reply_to_platform_msgid`.
- Backfill cursor persistence — today's backfill re-paginates from the latest sync token on every restart. MessageStore dedup makes this correct but wasteful on large rooms. Persisted resume tokens (likely a `CorpusCursor`-shaped row keyed by `(matrix, room_id, "backfill")`) when an operator hits a room large enough to feel it.

### Milestone 8 — Verifier tier — ✅ DONE (2026-05-24)

Third tier between the cheap Linker (signature-pairwise via `Comparator`)
and the future LLM Confirmer. Operates on raw per-actor corpora, returns
a composite score that promotes `PROPOSED → SUSPECTED` autonomously.
Fills the Spanish-linkage gap left by M5's blanket-disabled simhashes,
and generalizes beyond it.

- ✅ **`Verifier` Protocol + REGISTRY** (`eyenet/verifier/verifiers/{_base.py,__init__.py}`) — sibling of `Comparator`. `VerificationResult(method, score∈[0,1], confidence∈[0,1], evidence, skipped, skip_reason)`. Two methods ship: `GeneralImpostors` (Koppel/Schler, ~200 LOC, n_iters=100 bootstrap subsamples over function-word + char-trigram feature subspaces) and `CompressionDistance` (NCD via zlib, ~50 LOC, stdlib-only, symmetric concat, 50KB-cap window).
- ✅ **`VerifierService`** (`eyenet/verifier/service.py`) — `ServiceBase` subclass. Subscribes to `attribution.linkage.proposed`; dereferences last-N message bodies for both actors via MESSAGES engine; runs REGISTRY; composite = mean of non-skipped scores; if composite ≥ `composite_floor` → `LinkageStore.transition(SUSPECTED)` + emits `LinkageSuspectedEnvelope`. Audit-emits `verifier.evaluated` per verifier and `linkage.suspected` on promotion. Per-language disable honored via `VerifierThresholds.for_verifier(name, language) -> float | None`.
- ✅ **`VerifierThresholds`** (`eyenet/cli/config.py`) — mirrors `LinkerThresholds`: per-method float floors + `<method>_per_lang: dict[str, float | None]` overrides + `composite_floor` + `window_messages`. M8 ships GI/NCD enabled for all languages (no Spanish disable; the calibration grid will surface AUC).
- ✅ **`FeedbackPair` SQLite store** (`eyenet/models/feedback.py`, `eyenet/storage/feedback.py`) — auto-populated by the existing `eyenet linkage confirm` (→`ground_truth="same"`) and `eyenet linkage reject` (→`ground_truth="diff"`) commands. `suspect` does NOT write (still ambiguous). Colocated in the PROFILES engine so the `linkage_id` FK resolves natively. Pair-order invariant (`actor_a_id < actor_b_id`) enforced at both contract and DB layers, mirroring `LinkageStore`. Idempotent on `linkage_id` — operator overrides replace the prior row.
- ✅ **CLI**: new `eyenet verifier` push-mode runner (mirrors `eyenet linker`). `--impostor-pool` flag accepts a JSONL fixture; defaults to `tests/fixtures/calibration/impostor_pool.jsonl` if present, falls back to empty pool (GI degrades to plain cosine with confidence=0.3).
- ✅ **Calibration grid** (`eyenet/calibration/verifier_grid.py`) — score-higher-is-better mirror of `simhash_grid`. SAME pairs from per-sender `split_halves`, DIFF pairs sampled cross-sender (capped at 5x within count, seeded RNG for reproducibility). AUC via `mann_whitney_auc_higher_better`, 101-row sweep over [0,1] score thresholds, precision-floor + F1-max pickers. `VerifierGridResult` mirrors `PrimitiveGridResult` field-for-field.
- ✅ **Artifact extension** (`eyenet/calibration/artifact.py`) — schema 1.0 → 1.1 (additive). New `VerifierArtifactEntry` + `verifiers: tuple[...]` field on `CalibrationArtifact`. New `_ES_DISABLED_VERIFIERS` sibling set (empty on ship — GI/NCD are designed for short chat). Migration applied to committed `rutify_calibration_baseline.json` — `schema_version="1.1"`, `verifiers=()` for the M5/M6.5-era baseline; new self_hash `958d347e…`.
- ✅ **`eyenet calibrate run` wired** to emit the `verifiers` section alongside `simhash` and `recipes`. `eyenet calibrate report` renders the new section as a markdown table.
- ✅ **Tests**: 32 new unit tests across `tests/unit/verifier/` (5 files: Protocol contract, GI, NCD, VerifierThresholds, _bag) + 4 new `FeedbackPair` storage tests + 3 new integration tests (`tests/integration/test_verifier_pipeline.py` — same-author promoted, diff-author not promoted, short-corpus skip) + 9 new calibration tests (`tests/calibration/test_verifier_thresholds.py` — synthetic AUC floor, artifact roundtrip, schema 1.1 baseline, `_ES_DISABLED_VERIFIERS` empty policy).
- ✅ **Quality gates**: `pytest -m "unit or contract"` 628 green (was 581, +47). `pytest -m integration` 22 green (was 19, +3). `pytest -m calibration` 34 green (was 25, +9). `mypy --strict eyenet/` clean across 164 source files. `ruff check` clean. Coverage 87.38% (above 85% gate).
- ✅ **Live smoke**: `eyenet --help` shows the new `verifier` command. Verifier registry resolves GI + NCD at import; synthetic same/diff corpus separates cleanly (GI same=0.886 / diff=0.013; NCD same=0.569 / diff=0.358). FeedbackPair CRUD verified against a real SQLite file with linkage FK.

**Carries forward to M8.5 / M9 (deferred per the operator's M8-scope decision):**
- Sentence-transformer cosine verifier (heavyweight; needs operator decision on bundle-vs-BYO model).
- LR fusion (method 5) — gated on ≥50 confirmed pairs in `FeedbackPair`.
- TOML export of feedback pairs (`eyenet calibrate export-feedback`) — only needed when LR fusion lands.
- Real Rutify calibration run against the new verifier grid (corpus is gitignored; operator-triggered). Will update `rutify_calibration_baseline.json` with non-empty `verifiers` entries and may flip `_ES_DISABLED_VERIFIERS` per the AUC outcome.
- Re-enable the four ES-disabled signature simhashes when BEHAVE-TEXT 0.0.2 ships minhash-with-shingles.

**Gap-closure pass (2026-05-24, same-day-as-M8):** post-ship audit closed:
- ✅ **Behavioral bug — language propagation.** `VerifierService._extract_language` read `evidence["language"]` but the Linker never put it there. Fix in `eyenet/linker/linker.py::_emit_proposal` injects `slot_language` into the proposal evidence dict. Per-language disable path is now reachable at runtime. New unit tests `tests/unit/linker/test_language_propagation.py` cover the propagation + the no-language case.
- ✅ **Stable linkage_id across bus + DB.** Linker minted a fresh UUID for the bus envelope while `insert_proposed` minted a different one for the DB row — silently mismatched. Verifier transitions failed with "linkage not found" the first time anything tried to chain on the wire ID. `LinkageStore.insert_proposed` now accepts an optional `linkage_id`; Linker passes its envelope ID. Persist-before-publish ordering added to defeat the read race on real NATS.
- ✅ **`FeedbackPairRow` Pydantic schema** (`eyenet/contracts/feedback.py`) — sibling to the SQLModel `FeedbackPairTable`, mirrors the LinkageRow / LinkageTable split. Enforces `actor_a_id < actor_b_id` and `ground_truth ∈ {"same","diff"}` at the contract layer. Surface-gate test registers it as Surface=db. `FeedbackPairStore` ABC return types narrowed from `object` to `FeedbackPairRow`; SQLite impl converts at the boundary via `_row_to_contract`.
- ✅ **CLI integration tests** (`tests/integration/test_linkage_cli_feedback.py`) — `CliRunner` against `eyenet linkage {confirm,reject,suspect}` asserting state machine + FeedbackPair side-effects + terminal-state refusal.
- ✅ **E2E test against real NATS** (`tests/e2e/test_m8_nats_pipeline.py`, gated on `EYENET_E2E=1`) — propose→verify→suspected over wire for same-author corpora; no-promotion for diff-author. Confirmed running against `nats://127.0.0.1:4222`.
- ✅ **Synthetic impostor pool** at `tests/fixtures/calibration/impostor_pool.jsonl` — 12 actors × 30 messages across 6 Spanish + 6 English style buckets. GI now runs with confidence=1.0 out of the box (was degraded to confidence=0.3 plain-cosine fallback). Loader autopicks the path when `--impostor-pool` is unset.
- ✅ **Verifier syslog on promotion (#5)** — closed as no-op for codebase consistency. Linker and Graph don't syslog linkage state-machine events either; the convention is audit-only for that signal class. Documented inline.
- ✅ Final gates: 634 unit/contract, 26 integration (+4 CLI feedback), 34 calibration, 5 E2E (2 new M8 + 3 prior). Coverage 87.45%. `mypy --strict` clean across 165 files. `ruff check` clean.

### Milestone 8 — original design notes (for reference)

A third tier between the cheap Linker (signature-pairwise via `Comparator`)
and the LLM Confirmer (final arbiter). Operates on raw per-actor corpora
or one actor + one questioned document, returns a calibrated score. This
is what fills the Spanish-linkage gap until minhash lands, and the
generalization beyond it.

**New abstraction:** `Verifier` protocol — sibling to `Comparator`, but
takes two actors (or actor + questioned doc) and produces a
`VerificationResult(score, confidence, evidence)`. Registry pattern,
pluggable, audit-logged.

**Service shape:** new `eyenet/verifier/` subscribes to
`attribution.linkage.proposed`, runs the verifier registry on the
candidate pair, emits `attribution.linkage.suspected` when the composite
score clears a threshold. The existing `Linkage` state machine
(`PROPOSED → SUSPECTED → CONFIRMED/REJECTED`) and the Graph service
already accept this — no contract changes.

**Methods to ship (in this order — least-to-most heavyweight):**

1. **General Impostors (GI).** Koppel/Schler verification on an
   impostor pool. The Rutify corpus IS the impostor pool. Best fit for
   short Spanish chat where stylometry is structurally hard. ~200 LOC,
   no new deps. PAN-bake-off mature.
2. **Normalized Compression Distance (NCD).** `zlib`-based, raw-text,
   language-agnostic. Sidesteps the function-word domain limit entirely.
   ~50 LOC, stdlib only.
3. **Operator-confirmation feedback loop.** Every `LinkageConfirmed`
   becomes a positive labeled pair; every `LinkageRejected` becomes a
   negative. Persisted to `tests/fixtures/calibration/feedback_pairs.toml`
   (or an SQLite table — design TBD). Feeds the LR fusion table below.
4. **Cosine on multilingual sentence-transformer embeddings.** Probably
   the strongest single signal, but heaviest dependency (~400MB model
   download, optional GPU). Likely model:
   `paraphrase-multilingual-MiniLM-L12-v2`. Operator-opt-in via config.
5. **Likelihood-Ratio fusion.** Unifying composite scorer. Combines
   per-Verifier scores via LR tables calibrated on the feedback-loop
   labeled pairs. Forensic-stylometry standard. Gated on (3) producing
   ≥50 labeled positive pairs.

**Methods deferred / skipped:**

- **Burrows' Delta / Cosine Delta.** Designed for novel-length texts.
  Diminishing returns over GI + simhash on short chat. Revisit only if a
  long-form corpus lands.

**Calibration plumbing the artifact reuses:**

- `eyenet/calibration/recipes_grid.py` AND-of-axes / OR-of-groups
  Picker generalizes to Verifier-score fusion: every Verifier becomes
  one axis in an LR group. M5's labels TOML schema + corpus-sha256
  pinning carry over verbatim.
- The committed feedback-pairs TOML (post-(3)) is the LR fusion's
  training input — produced as a side-effect of operator activity, not
  hand-labeled.

**Open design questions (decide at M7 kickoff):**

- Pull or push? Verifier service either subscribes to
  `LinkageProposed` (push, runs on every proposal) or exposes a CLI for
  operator-on-demand verification (pull, runs only when asked). Pull is
  cheaper; push catches more.
- Bodies-on-the-bus or dereference-at-Verifier? The Verifier needs
  evidence bodies, which the `LinkageProposed` envelope doesn't carry
  today. Either expand the envelope (heavier bus traffic) or have the
  Verifier dereference via `MessageStore` (more audit-log volume).
  M4 §4.3 leans toward the latter.
- Embedding model deployment: bundle the model with EYENET releases vs.
  operator-brings-their-own. The 400MB bundle changes the
  small-operator-friendly story — flagged for operator decision.

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
