# EYENET — Data Models (on paper, v0)

> SQLModel + Pydantic v2. Single source of truth for both wire schemas and DB schemas where they coincide; separate models where they diverge (bus envelopes vs persisted rows).

This document is **a discussion artifact**. Field types, names, and decisions are open. Write down disagreements, then we revise, then we code.

---

## 0. Naming & ID conventions

- **Primary keys:** UUIDv7 (time-ordered, indexable) on every entity unless otherwise noted. `id: UUID = Field(default_factory=uuid7)`.
- **Opaque actor join key:** in addition to UUID PK, every Actor has `actor_key: str` = `"actor:" + sha256(source_kind || platform_userid)`. Stable across DB resets, used in trace/log/bus contexts.
- **Timestamps:** UTC, ISO8601, `datetime` with `tzinfo`. Two timestamp pairs everywhere relevant: `*_at_source` (when the platform says it happened) and `*_at_ingest` (when EYENET saw it).

---

## 1. Models you proposed

### 1.1 `Source`
A specific origin. **Telegram has one Source row; each forum platform is its own Source row.** Distinct from `SourceKind` (the enum). A single web/forum Source can own multiple domains, subdomains, and onion mirrors — see §2.26 `SourceDomain`.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `kind` | `SourceKind` enum | `telegram`, `matrix`, `irc`, `discord`, `forum`, `rss`, `xmpp`, ... |
| `display_name` | str | "Telegram", "Example Forum (forum.example.com + mirrors)" |
| `canonical_url` | str \| None | display-only; the URL the operator wants the UI to deep-link to. NOT a matching key — matching is done via `SourceDomain` rows. Null for non-web sources (Telegram, Matrix, IRC). **Constraint:** when non-null, its hostname (after punycode normalization per §2.26) MUST equal the `pattern` of this Source's `is_primary=TRUE, removed_at IS NULL` `SourceDomain` row. Enforced at `create_source`, `update_source`, and any operation that changes the primary pattern. |
| `created_at` | datetime | |
| `notes` | str \| None | operator scratchpad |

**Important:** `Source` does NOT carry credentials (Credentials = `Identity`, §2.1) and does NOT carry matching keys (Hostnames/patterns = `SourceDomain`, §2.26). `canonical_url` is for the operator's browser, not for the bridge resolver.

### 1.2 `Actor`
The person/entity being observed. NOT the operator's identity.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actor_key` | str unique index | `"actor:<sha256>"` |
| `source_id` | FK → Source | which platform first saw them |
| `platform_userid` | str | platform-native, retained (operator-grade) |
| `current_handle` | str \| None | most recent observed |
| `current_display_name` | str \| None | |
| `first_seen_at_source` | datetime \| None | platform-reported |
| `first_seen_at_ingest` | datetime | when EYENET first saw them |
| `last_seen_at_source` | datetime \| None | |
| `last_seen_at_ingest` | datetime | |
| `is_bot_self_declared` | bool | platform-flagged bot? |
| `notes` | str \| None | |

### 1.3 `Group`
Chat / channel / forum thread / room.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `source_id` | FK → Source | |
| `platform_groupid` | str | telegram chat_id, forum thread_id, etc. |
| `kind` | `GroupKind` enum | `chat`, `channel`, `dm`, `forum_thread`, `irc_channel`, `matrix_room` |
| `current_title` | str \| None | |
| `current_description` | str \| None | |
| `is_public` | bool \| None | |
| `member_count` | int \| None | last-known |
| `first_seen_at_ingest` | datetime | |
| `last_observed_at_ingest` | datetime | |

### 1.4 `Message`
Atomic content unit.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `source_id` | FK → Source | |
| `group_id` | FK → Group | |
| `actor_id` | FK → Actor | |
| `platform_msgid` | str | |
| `evidence_ref` | str unique index | `"telegram:<chat_id>:<msg_id>"` etc. |
| `body` | str | full content, retained |
| `body_lang` | str \| None | BCP-47, detected |
| `length_chars` / `length_words` | int | denormalized for fast filters |
| `sent_at_source` | datetime | |
| `ingested_at` | datetime | |
| `reply_to_msg_id` | UUID \| None FK self | |
| `forward_of_msg_id` | UUID \| None FK self | |
| `forward_origin_actor_id` | UUID \| None FK Actor | for forwards from outside our visibility |
| `has_attachment` | bool | |
| `source_specific` | dict (JSON) | platform-shaped extras |

---

## 2. What you're missing

### 2.1 `Identity` — the OPERATOR's persona
Not the actor. This is the credential/persona EYENET *uses to observe*. Lives in the pool. **Encrypted at rest.**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | str unique | `tg_alpha`, `forum_lurker_03` |
| `source_id` | FK → Source | which platform this identity authenticates to |
| `session_path` | str | path on disk to encrypted session blob |
| `proxy_uri` | str \| None | tor/socks/http proxy |
| `cooldown_seconds` | int | min gap between sessions |
| `last_used_at` | datetime \| None | |
| `state` | enum | `available`, `in_use`, `cooling`, `frozen`, `burned` |
| `notes` | str | |

### 2.2 `Membership` — Actor ↔ Group
Different signal than messaging. Lurkers join without speaking. Admins are admins even when silent.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actor_id` / `group_id` | FK | unique together |
| `role` | enum | `member`, `admin`, `owner`, `restricted`, `banned`, `unknown` |
| `joined_at_source` | datetime \| None | platform-reported, often unavailable |
| `joined_at_ingest` | datetime | first time we saw them in this group |
| `left_at_ingest` | datetime \| None | |

### 2.3 `Observation` (persisted form)
Bus envelope = `decnet_behave_text.spec.Observation` (we don't redefine). DB row is its persisted twin, indexed for retrieval.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actor_id` | FK | |
| `evidence_ref` | str index | message that produced it (or `null` for window-aggregate observations) |
| `primitive_namespace` | str | `stylometric`, `lexical`, ... |
| `primitive_name` | str | `function_word_distribution_top50` |
| `primitive_version` | str | `0.2` |
| `value_kind` | enum | `hash`, `numeric`, `enum_str`, `array_str`, `array_numeric` |
| `value_hash` | str \| None | for `hash` kind |
| `value_numeric` | float \| None | |
| `value_enum` | str \| None | |
| `value_array` | list[str] \| None | as JSON; for `array_str` kind |
| `value_array_numeric` | list[float] \| None | as JSON; for `array_numeric` kind (e.g. token-length distributions, per-bucket histograms) |
| `window_start` / `window_end` | datetime \| None | for window-aggregate observations |
| `observed_at` | datetime | when sensor computed it |
| `sensor_instance` | str | for trace correlation |

**Index:** `(actor_id, primitive_name, observed_at DESC)` — the engine's hot path.

### 2.4 `Profile` (current + historical)
Current row per actor + append-only history.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actor_id` | FK | |
| `version` | int | monotonic per actor |
| `is_current` | bool | exactly one per actor true |
| `role_signal` | enum \| None | `credential_broker`, `low_skill_buyer`, `group_admin`, ... per recipes |
| `role_confidence` | float | [0,1] |
| `stylometric_summary` | dict (JSON) | hash digest of last-known primitive values |
| `lexical_summary` | dict (JSON) | |
| `temporal_summary` | dict (JSON) | |
| `interaction_summary` | dict (JSON) | |
| `network_summary` | dict (JSON) | |
| `content_summary` | dict (JSON) | experimental; weight skeptically |
| `derived_at` | datetime | when this version was emitted |
| `derived_from_observation_count` | int | for explainability |

Open question (already in PLAN §11.2): snapshot-per-update vs event-sourced. Above is snapshot. Lean toward keeping it snapshot for v0.

### 2.5 `Linkage`
Proposed/confirmed actor↔actor link. Source of truth for the cross-platform identity story.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actor_a_id` / `actor_b_id` | FK | unordered; enforce `a < b` lexicographic on UUIDv7 (= `a` was created first) **for dedup only — carries NO semantic weight**. `a` is NOT "the canonical actor" of the pair |
| `state` | enum | `proposed`, `confirmed`, `rejected`, `superseded` |
| `method` | str | `function_word_simhash_hamming`, `handle_match`, `manual`, ... |
| `score` | float | normalized [0,1] |
| `evidence` | dict (JSON) | distance, threshold, primitives consulted, span_id |
| `proposed_at` | datetime | |
| `decided_at` | datetime \| None | |
| `decided_by` | str \| None | `linker:auto`, `operator:<id>` |

### 2.6 `Persona` / `ActorCluster`
The constructed cross-platform identity. Built from confirmed `Linkage` rows.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `label` | str \| None | operator-assigned ("RutifyAdminMain") |
| `member_actor_ids` | list[UUID] | **forward view** — denormalized JSON list, cheap to read, rebuildable from linkages. Use this when you have a `persona_id` and want its members. **Do NOT** scan this column to answer "which Persona contains actor X?" — that's what `PersonaMembership` is for. |
| `created_at` / `updated_at` | datetime | |

### 2.6a `PersonaMembership` — Persona ↔ Actor (reverse-indexable)
Companion to §2.6. The denormalized JSON list on `Persona` is unindexable in SQLite for reverse lookups (`actor_id → persona_id`). This join table is the indexed reverse view. Both representations are rebuildable from confirmed `Linkage` rows; they MUST be kept in sync by the same transaction that mutates `Persona`.

| Field | Type | Notes |
|---|---|---|
| `persona_id` | FK → Persona, composite PK | |
| `actor_id` | FK → Actor, composite PK | unique — an actor belongs to AT MOST one Persona at a time |
| `joined_at` | datetime | when this membership was established |
| `via_linkage_id` | FK → Linkage \| None | the confirmed linkage that placed this actor in the persona; null for operator-manual placement |

**Indexes:** `(actor_id)` for the reverse lookup; `(persona_id)` already covered by composite PK.

**Invariant:** `Persona.member_actor_ids` is the sorted union of `PersonaMembership.actor_id WHERE persona_id = Persona.id`. A periodic consistency check (`tools/persona_audit.py`, post-v0) verifies this; for v0, it's enforced by writing through a single `PersonaStore.add_member()` API.

### 2.7 `InfrastructureArtifact`
Wallets, PGP keys, domains, phone numbers, emails, cross-platform handles, onion addresses. The Actor↔Infrastructure relation in the goals. Also the substrate for cross-source bridge resolution (see §2.25).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `kind` | enum | `wallet_btc`, `wallet_xmr`, `wallet_eth`, `pgp_key`, `domain`, `onion`, `email`, `phone`, `handle_other_platform`, `paste_url` |
| `value` | str | normalized form |
| `value_hash` | str index | `sha256(value)` for fast lookup |
| `first_seen_at_ingest` | datetime | |
| `last_seen_at_ingest` | datetime | |
| `resolved_to_source_id` | UUID \| None FK Source | populated when this artifact corresponds to a configured Source (e.g. `domain="forum.example.com"` matches a MyBB Source's `base_url`); null until a match exists |
| `resolution_state` | enum | `unresolved` (default — no matching Source), `resolved` (FK populated, single match), `ambiguous` (multiple Sources matched — operator must disambiguate), `irrelevant` (operator marked: not worth monitoring), `pending_source` (operator flagged: "I'd configure a Source for this if/when I have time"), `not_applicable` (kind that can't be source-bound — e.g. `wallet_btc`, `pgp_key`, `phone`) |

**Index:** `(resolution_state, kind)` for the operator's "infrastructure waiting to be bridged" view; `(resolved_to_source_id)` for the reverse lookup ("which artifacts already point at this Source").

**`resolution_state` derivation rules:**
- `kind ∈ {wallet_btc, wallet_xmr, wallet_eth, pgp_key, email, phone}` → always `not_applicable`. Wallets and PGP keys are not Sources; emails and phones are identifiers, not platforms. These rows never get a `resolved_to_source_id`.
- `kind ∈ {domain, onion, paste_url}` → eligible for resolution; default `unresolved`, transitions via §2.25 invariant.
- `kind = handle_other_platform` → deferred. Handle ↔ Source resolution requires identity-linkage machinery that doesn't exist yet (a `@username` on a future Twitter Source might be the same person as a known Telegram actor — that's §2.5 `Linkage` territory, not §2.25 bridge resolution). Stays `unresolved` indefinitely until linkage work lands.

### 2.8 `ActorArtifact` — Actor ↔ Infrastructure join
| Field | Type | Notes |
|---|---|---|
| `actor_id` / `artifact_id` | FK, composite PK | |
| `first_seen_evidence_ref` | str | which message established the link |
| `confidence` | float | |

### 2.9 `Attachment`
Attachment metadata, NOT the binary. The binary stays in object storage if retained at all.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `message_id` | FK | |
| `kind` | enum | `image`, `video`, `audio`, `document`, `sticker`, `voice`, `other` |
| `mime` | str | |
| `size_bytes` | int | |
| `sha256` | str index | content hash if downloaded |
| `filename` | str \| None | |
| `storage_uri` | str \| None | local path / object key, null if not retained |

### 2.10 `ActorAliasHistory`
People rename. We keep history.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actor_id` | FK | |
| `kind` | enum | `handle`, `display_name`, `username` |
| `value` | str | |
| `observed_from` / `observed_until` | datetime | until = null = current |

### 2.11 `GroupSnapshot`
Groups also evolve (title, description, member count, public/private flips).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `group_id` | FK | |
| `title` / `description` | str \| None | |
| `member_count` | int \| None | |
| `is_public` | bool \| None | |
| `observed_at` | datetime | |

### 2.12 `IdentityLabel`
Operator-supplied ground-truth labels. Engine input (per BEHAVE-TEXT attribution-recipes).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actor_id` | FK | |
| `label` | str | free-form or recipe-aligned: `credential_broker`, `confirmed_X` |
| `confidence` | enum | `low`, `medium`, `high`, `certain` |
| `applied_by` | str | operator id |
| `applied_at` | datetime | |
| `rationale` | str | |

### 2.13 `EngagementAuthorization`
Operator records "we are authorized to interact with this actor / in this group". Out of scope for v0 *behavior* but in scope for v0 *contract*, since BEHAVE-TEXT envelope schemas reference it.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `subject_kind` | enum | `actor`, `group` — discriminator for the FK |
| `actor_id` | UUID \| None FK Actor | non-null iff `subject_kind = 'actor'` |
| `group_id` | UUID \| None FK Group | non-null iff `subject_kind = 'group'` |
| `authorized_by` | str | system_user id |
| `authorized_at` | datetime | |
| `scope` | enum | `observe_only`, `passive_engage`, `active_engage` |
| `expires_at` | datetime \| None | |

**Mechanism:** Pydantic discriminated union on `subject_kind` for the contract layer; DB-level `CHECK ((actor_id IS NOT NULL) <> (group_id IS NOT NULL))` to enforce exactly-one-of. No nullable union types — explicit columns + check constraint, because SQLite-friendly and migration-friendly.

### 2.14 `AuditLog`
The `eyenet.audit.*` stream, persisted. Append-only. Operator-relevant events only — NOT a firehose.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `event` | str | `evidence_access`, `identity_pool.rotated`, `label.applied`, `kill_switch`, `linkage.confirmed`, `linkage.rejected`, `case.opened`, `case.closed`, `tier.transition`, `system_user.login`, `system_user.permission_change`, ... |
| `service` | str | which EYENET service emitted it |
| `instance_id` | str | |
| `system_user_id` | UUID \| None FK SystemUser | when operator-initiated |
| `subject_kind` | str | `actor`, `group`, `message`, `identity`, `linkage`, `case`, `system_user` |
| `subject_id` | UUID \| None | |
| `evidence_ref` | str \| None | |
| `trace_id` / `span_id` | str \| None | |
| `payload` | dict (JSON) | event-specific |
| `at` | datetime | |
| `prev_hash` | str | sha256 of previous AuditLog row (chained for tamper-evidence) |
| `self_hash` | str | sha256 of this row's canonicalized fields |

**Tamper-evidence:** AuditLog is hash-chained. Each row's `prev_hash` references the previous row's `self_hash`. Breaking the chain (insertion, deletion, edit) is detectable with one walk. Cheap, append-only-friendly, no fancy crypto needed.

### 2.15 `SystemUser`
The operator(s) of EYENET itself. Multi-user is in scope per PLAN §12 (revised 2026-05-04). v0 ships with single-user-default but the model supports N from the start (per the "design plural from day one" principle).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `username` | str unique | |
| `display_name` | str | |
| `email` | str \| None | |
| `password_hash` | str | argon2id; never plaintext |
| `role` | enum | `admin`, `analyst`, `viewer` (room to grow) |
| `is_active` | bool | |
| `last_login_at` | datetime \| None | |
| `created_at` | datetime | |
| `mfa_secret_encrypted` | str \| None | TOTP secret (age-encrypted), optional in v0 |
| `notes` | str \| None | |

**Permissions (sketch, v0):**
- `admin` — everything, including SystemUser CRUD, identity pool ops, kill switch.
- `analyst` — read all, write labels/cases/linkage decisions, dereference evidence.
- `viewer` — read-only, evidence dereference still audited.

**Open question:** session/token model. Lean: short-lived JWT signed with operator-keyring key, refresh-token rotation. CLI uses a longer-lived token in the keyring. Decide at the time we build the API surface.

### 2.16 `SystemLog`
Significant operational events persisted for in-app queryability. **NOT a firehose.** Debug/info chatter stays in stdout/journald per PLAN §9.4 — that's a high-volume stream that doesn't belong in SQLite.

What lands here:
- `warn` and `error` levels (always).
- Lifecycle events deemed operator-visible (service start/stop, identity-pool state changes, NATS reconnect, contract-version mismatch handled by fallback).
- Anything with a structured event name in a curated allowlist.

What does **not** land here:
- `debug` and most `info` lines — journald only.
- Per-message processing chatter — traces cover that.
- AuditLog events — those have their own table (no double-write).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `level` | enum | `warn`, `error`, `lifecycle`, `notice` (no `debug`/`info`) |
| `service` | str | |
| `instance_id` | str | |
| `event` | str | dotted event name from allowlist |
| `message` | str | human-readable summary (one line) |
| `trace_id` / `span_id` | str \| None | |
| `error_type` | str \| None | exception class name when applicable |
| `error_message` | str \| None | |
| `stack_hash` | str \| None | sha256 of normalized stack — group identical errors |
| `fields` | dict (JSON) | structured context |
| `at` | datetime | |

**Index:** `(service, level, at DESC)` for the operator log view; `(stack_hash, at DESC)` for "show me all instances of this error".

**Retention:** SystemLog rows older than N days (default 90) move to cold tier per PLAN §5.1. AuditLog never auto-prunes — that's evidence.

### 2.17 `Case`
Operator's investigation grouping. Drives hot/cold/archived tier transitions per §5.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | str | "Rutify-Q2-2026" |
| `state` | enum | `open`, `closed`, `archived` |
| `opened_at` / `closed_at` | datetime | |
| `actor_ids` / `group_ids` | list[UUID] | scope of the case |
| `notes` | str | |

### 2.18 Internal: `CorpusCursor`
Sensor's bookmark per actor. Not exposed; here so it isn't forgotten.

| Field | Type | Notes |
|---|---|---|
| `actor_id` | FK PK | |
| `primitive_name` | str | composite PK with actor_id |
| `last_processed_msg_ts` | datetime | |
| `last_processed_msg_id` | UUID | |

### 2.19 `Collector`
A configured, runnable observer instance. The thing that actually pulls bytes off a platform. Distinct from `Source` (the platform) and `Identity` (the credential it consumes). One `Source` + one `Identity` can produce N `Collector` rows with different scopes (different chats, different rate caps, different proxy).

The supervisor (`CollectorSupervisor`, single in-process service) reconciles `desired_state` → `observed_state` in a tick loop, leases the bound `Identity` out of the pool on start, releases on stop/crash, and emits lifecycle events to SystemLog. See API_PLAN §4.11 for the runtime model.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `source_id` | FK → Source | which platform — telegram/matrix/forum/... |
| `identity_id` | FK → Identity, unique | exclusive lease; one Identity backs at most one Collector at a time |
| `kind` | `CollectorKind` enum | `telegram`, `matrix`, ... runtime discriminator; mirrors `Source.kind` |
| `instance_name` | str unique | operator-assigned label — `tg_alpha_collector_01` |
| `config` | dict (JSON) | source-specific: `monitor_chat_ids`, `monitor_rooms`, `rate_limit_per_min`, `proxy_uri_override`, ... validated by Pydantic discriminated union on `kind` |
| `desired_state` | enum | `stopped`, `running`, `disabled` — operator intent; the only field UI mutates for lifecycle |
| `observed_state` | enum | `stopped`, `starting`, `running`, `cooling`, `crashed` — supervisor-written, never operator-written |
| `last_heartbeat_at` | datetime \| None | last tick the collector reported alive |
| `last_started_at` | datetime \| None | |
| `last_stopped_at` | datetime \| None | |
| `last_error_type` | str \| None | exception class on most recent crash |
| `last_error_message` | str \| None | one-line summary on most recent crash |
| `last_error_at` | datetime \| None | |
| `restart_count` | int | monotonic since `last_started_at` reset; backoff hint for supervisor |
| `created_at` | datetime | |
| `created_by` | FK → SystemUser | |
| `notes` | str \| None | |

**Indexes:** `(source_id)`, `(observed_state)` for fleet-health views, `(identity_id)` unique to enforce the exclusive lease.

**Invariant — `desired_state` vs `observed_state` are separate fields, both persisted.** Operator intent and supervisor reality are independently observable; reconciliation drift is itself a signal. A row with `desired_state=running` and `observed_state=crashed` for >N ticks is what the dashboard alerts on.

**Lifecycle events** ride on SystemLog (§2.16) with the curated event names `collector.started`, `collector.stopped`, `collector.crashed`, `collector.cooling`, `collector.identity_lease_released`, `collector.config_changed`. No third table.

**Config is sensitive.** `config` may contain identity-binding details (chat IDs the operator is observing, proxy URIs revealing OPSEC posture). Treated as `restricted` tier for read (§4.7 of API_PLAN); the `viewer` role sees `desired_state`/`observed_state`/`last_*` only — never the config blob.

**Identity discriminator** (extension to §2.1 `Identity`): adds `role: IdentityRole` enum with values `monitor` (graduated, used for sustained observation), `scout` (newly-minted, used to test-join candidate groups before promotion), `quarantine` (post-incident, parked). Default `monitor`. The supervisor (§2.20-§2.21 discovery flow) prefers `scout` identities for auto-joins of new candidates and graduates them to `monitor` after a configurable observation window (default 7 days, no flags raised).

**Max auto-discovery depth** (extension to `Collector.config`): each kind-specific config carries `max_auto_join_depth: int = 2`. Operator-seeded groups are depth 0; what they mention is depth 1; what those mention is depth 2. Depth >2 requires operator promotion of an interior node to a new root (audit event `collector.root_promoted`).

### 2.20 `GroupCandidate`
A group discovered through cross-references but not yet joined by any collector. The waiting room for the discovery loop. Global — one row per `(source_id, platform_groupid)` regardless of how many collectors have observed it being mentioned.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `source_id` | FK → Source | |
| `platform_groupid` | str | telegram chat_id, matrix room alias, etc. — composite unique with `source_id` |
| `kind_hint` | `GroupKind` enum \| None | best-effort from mention context — `channel` if `t.me/X` resolved to a channel, `chat` if a group invite link, null if unknown |
| `display_name_hint` | str \| None | from the mention context — e.g. forwarded-from header, link preview title |
| `state` | enum | `discovered`, `queued`, `approved`, `joining`, `joined`, `rejected`, `failed`, `parked` |
| `score` | float | aggregate signal strength; recomputed when new mentions arrive |
| `score_breakdown` | dict (JSON) | `{distinct_mentioning_groups, distinct_mentioning_actors, recency_decay, role_signal_boost}` — explainability |
| `first_observed_at_ingest` | datetime | when first GroupCandidateMention landed |
| `last_observed_at_ingest` | datetime | when the most recent mention landed |
| `reviewed_at` | datetime \| None | when operator (or auto-policy) transitioned out of `discovered`/`queued` |
| `reviewed_by` | str \| None | `auto:policy` or `operator:<system_user_id>` |
| `rejection_reason` | str \| None | free-text when `state = rejected` |
| `assigned_collector_id` | UUID \| None FK Collector | which collector will execute the join when `state = approved`; null for `discovered`/`queued`/`rejected` |
| `resulting_group_id` | UUID \| None FK Group | populated when `state = joined` — links the candidate to the real Group row created on successful join |

**Indexes:** `(source_id, platform_groupid)` UNIQUE — same group never gets two candidate rows. `(state, score DESC)` for the operator's triage queue. `(assigned_collector_id, state)` for the supervisor's "what do I need to act on" tick query.

**State machine:**
```
discovered → queued → approved → joining → joined
              │           │          │       │
              ↓           ↓          ↓       │
           rejected    rejected   failed     │
              │                              │
              └──── parked ──────────────────┘
```
- `discovered` = newly inserted, score still accreting from new mentions.
- `queued` = score crossed the auto-queue threshold; visible in the operator UI.
- `approved` = operator (or auto-policy if enabled) signed off; `assigned_collector_id` resolved.
- `joining` = supervisor issued the join command; awaiting platform confirmation.
- `joined` = `resulting_group_id` populated; rows now flow through normal Message pipeline.
- `rejected` = operator declined or auto-policy filtered out; no retry without explicit operator action.
- `failed` = join attempt failed at the platform layer (banned, invite-link expired, anti-spam triggered); supervisor backs off, may retry per policy.
- `parked` = formerly `joined`, but the collector left (operator-initiated or supervisor-detected ban). Distinct from `rejected` — we WERE in, we're not anymore. Re-entry is a fresh operator decision.

### 2.21 `GroupCandidateMention`
One row per signal that points to a `GroupCandidate`. The provenance trail. Multiple collectors observing the same mention each add a row. Multiple mentions across different paths each add a row. This is the substrate for the score function AND for the per-collector eligibility evaluation in §2.19.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `candidate_id` | FK → GroupCandidate | |
| `observed_by_collector_id` | FK → Collector | which collector saw the mention |
| `observed_in_group_id` | FK → Group | which already-joined group contained the mention |
| `seed_root_id` | FK → Group \| None | the operator-seeded root group this trail descends from; null if the mention came from a group whose own provenance is not from a seed (rare; happens when groups are operator-added manually mid-investigation) |
| `depth_from_root` | int | 0 for direct seeds, N for the leaf N hops from the root |
| `mention_evidence_ref` | str | `"telegram:<chat_id>:<msg_id>"` — the specific Message that contained the mention |
| `mention_kind` | enum | `invite_link`, `username_mention`, `forward_origin`, `link_preview`, `bio_link`, `other` |
| `mentioned_at_source` | datetime | when the mention was sent on the platform |
| `mentioned_at_ingest` | datetime | when EYENET ingested the mention |
| `mentioning_actor_id` | FK → Actor | who made the mention |
| `mentioning_actor_role_signal` | str \| None | snapshot of `Profile.role_signal` at observation time — frozen, not a live FK to avoid retroactive score drift |

**Indexes:** `(candidate_id, depth_from_root ASC)` — for resolving the minimum-depth path per candidate. `(observed_by_collector_id, mentioned_at_ingest DESC)` — for "what did A discover this week." `(seed_root_id)` — for "if I retire this root, which candidates lose provenance?"

**Per-collector eligibility computation** (the answer to "A is at depth limit but B isn't"):
```
eligible(collector C, candidate Z):
    min_depth_for_C = min(
        m.depth_from_root
        for m in Z.mentions
        if m.seed_root_id ∈ C.reachable_roots
    )
    return min_depth_for_C ≤ C.config.max_auto_join_depth
```
The candidate is global; the depth computation is per-collector against ITS reachable roots. A's discovery contributes to Z's mention pool even when A itself is not eligible to join Z.

### 2.22 `CollectorGroupMembership`
Which collectors are in which groups. The dedup-prevention and dual-cover-policy substrate. Distinct from `Membership` (§2.2), which tracks **observed-actor** ↔ group; this table tracks **operator-controlled-collector** ↔ group.

| Field | Type | Notes |
|---|---|---|
| `collector_id` | FK → Collector | composite PK |
| `group_id` | FK → Group | composite PK |
| `joined_at` | datetime | when this collector's identity entered the group |
| `joined_via` | enum | `seed` (operator-configured initial scope), `candidate` (came through §2.20-§2.21 discovery), `manual` (operator added mid-investigation through the UI), `restored` (the collector was banned and a replacement identity rejoined) |
| `joined_via_candidate_id` | FK → GroupCandidate \| None | populated iff `joined_via = candidate` |
| `left_at` | datetime \| None | populated when the collector leaves (operator stop, ban, identity-burn); row is retained for audit |
| `left_reason` | str \| None | `operator_stop`, `banned`, `identity_burned`, `policy_eviction`, `failed` |

**Indexes:** `(group_id, left_at)` — for "who is currently in X" (filter `left_at IS NULL`) AND "who was ever in X" (no filter). `(collector_id, left_at)` — for "what is A currently observing." `(group_id, left_at IS NULL)` partial — fast count for the dual-cover policy check.

**Used by:**
- **Dedup-on-join:** before approving a candidate, supervisor queries `count(*) WHERE group_id = Z.resulting_group_id AND left_at IS NULL`. Combined with `Case.redundancy_policy` (extension below), decides whether B's join is permitted.
- **OPSEC tracing:** "this leaked screenshot's `evidence_ref` is `telegram:X:Y` — which of our collectors were in X at time Y?" Cross-reference `Message.sent_at_source` with `CollectorGroupMembership.joined_at`/`left_at`.
- **Loss-of-coverage alerts:** if a collector goes to `observed_state=crashed` and was the sole member of a high-value group (`Case.redundancy_policy = required_dual` and only one membership row remains), emit `case.coverage_degraded` to SystemLog.

### 2.23 `MessageObservation`
Records that a specific collector observed a specific message. The dual-sighting audit row. The `Message` row itself is deduplicated by `evidence_ref` (one Message regardless of how many collectors saw it); this table preserves the multiplicity.

| Field | Type | Notes |
|---|---|---|
| `message_id` | FK → Message | composite PK |
| `collector_id` | FK → Collector | composite PK |
| `observed_at_ingest` | datetime | when THIS collector pulled THIS message off the platform — distinct from `Message.ingested_at` which is first-sight |
| `was_first_sighting` | bool | true iff this collector's INSERT created the Message row; false iff a prior collector already had |

**Indexes:** `(message_id)` for "who saw this." `(collector_id, observed_at_ingest DESC)` for "what did A pull recently." `(collector_id, was_first_sighting)` for collector throughput metrics (first-sightings are the meaningful work; secondary observations are dual-cover insurance).

**Write path:** Collector emits a `RawMessage` envelope. Storage performs `INSERT ... ON CONFLICT (evidence_ref) DO NOTHING` on `Message`; the affected-row-count tells the caller whether it was first-sighting. EITHER WAY, a `MessageObservation` row is then inserted unconditionally with `was_first_sighting` set accordingly. Sensor primitives run only on first-sighting (Observation pipeline is keyed by `message_id`, not `collector_id` — running them twice would double-count).

**Why not put `collector_id` directly on `Message`:** because the relationship is many-to-many under dual-cover policy. The first-sighting collector is recoverable (`SELECT collector_id FROM message_observation WHERE message_id = X AND was_first_sighting = TRUE`) without polluting the Message row.

### 2.24 `GroupAccessArtifact`
A known way to access a group (or a candidate not yet joined). One-to-many with `Group` / `GroupCandidate`: a single channel commonly carries multiple artifacts — a public username, a posted invite link, a forward-derived `t.me` link, a QR code captured from a sticker — all pointing to the same destination, each with its own validity lifecycle.

Cross-platform by design. Telegram, WhatsApp, Matrix, Discord, Signal, IRC all have analogous access vectors with platform-specific quirks; the `kind` enum stays neutral, platform details go in `details`.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `subject_kind` | enum | `group`, `candidate` — discriminator for the FK pair |
| `group_id` | UUID \| None FK Group | non-null iff `subject_kind = 'group'` |
| `candidate_id` | UUID \| None FK GroupCandidate | non-null iff `subject_kind = 'candidate'` |
| `kind` | `GroupAccessKind` enum | see below |
| `value` | str \| None | the identifier — `@rutify`, `t.me/+abc123`, `#room:matrix.example.com`, `chat.whatsapp.com/X`, `discord.gg/X`, `signal.group/#X`; null for kinds where there is no transferable token (e.g. `direct_invite`, `access_blocked`) |
| `details` | dict (JSON) | platform-specific extras: Matrix `via_servers`, Telegram invite-link `usage_limit` / `usage_count`, WhatsApp QR-payload metadata, Discord vanity vs standard invite, IRC channel modes |
| `discovered_via_mention_id` | UUID \| None FK GroupCandidateMention | back-reference; null for operator-supplied artifacts or artifacts learned post-join from the platform itself |
| `discovered_at_ingest` | datetime | |
| `last_validated_at` | datetime \| None | when EYENET last confirmed the artifact resolves to the expected destination (Telethon `get_entity` succeeded, invite preview returned 200, Matrix `/_matrix/client/v3/directory/room/{alias}` resolved, etc.) |
| `validation_state` | enum | `unverified`, `valid`, `expired`, `revoked`, `usage_exhausted`, `blocked_for_our_identity`, `unknown_failure` |
| `requires_admin_approval` | bool | true for groups where the artifact exists publicly but join requires an admin click (Telegram restricted channels, Matrix knock-room, Discord membership-screening); supervisor will not auto-approve on these without `admin:candidates` |
| `expires_at` | datetime \| None | platform-reported when available (Telegram invite links carry expiry; WhatsApp v3 invite links can be time-limited; Matrix permalinks don't expire but the underlying alias can be removed); null otherwise |

**Indexes:** `(group_id, validation_state, kind)` partial WHERE `group_id IS NOT NULL` — "give me a valid artifact for X right now." `(candidate_id, validation_state, kind)` partial WHERE `candidate_id IS NOT NULL` — same, for pre-join. `(value, kind)` — collision detection across groups (one invite link should only ever resolve to one group; two rows = anti-spam or platform abuse signal).

**Constraint:** `CHECK ((group_id IS NOT NULL) <> (candidate_id IS NOT NULL))` — exactly one. Mirrors §2.13 `EngagementAuthorization`'s discriminated-union pattern; SQLite-friendly, migration-friendly, no nullable union types.

**`GroupAccessKind` enum — platform-neutral:**

| Kind | Telegram | Matrix | WhatsApp | Discord | Signal | IRC |
|---|---|---|---|---|---|---|
| `public_identifier` | `@username` | `#alias:server` | — | vanity URL | — | `#channel` |
| `invite_link` | `t.me/+X`, `t.me/joinchat/X` | `matrix.to/#/!roomid?via=...` | `chat.whatsapp.com/X` | `discord.gg/X` | `signal.group/#X` | — |
| `qr_code` | encodes invite_link | encodes matrix.to URL | encodes chat.whatsapp.com | encodes discord.gg | encodes signal.group | — |
| `direct_invite` | added by existing member | `m.room.member` invite | admin-add | direct invite | admin-add | `INVITE` cmd |
| `paid_subscription` | Premium tier channels | — | — | boost-locked servers | — | — |
| `access_blocked` | geoblocked / banned identity | server-side ACL | — | server-side block | — | bans / +k key |
| `restricted_other` | catch-all | catch-all | catch-all | catch-all | catch-all | catch-all |

Platform-specific quirks ride in `details`:
- **Telegram invite link**: `{"usage_limit": 100, "usage_count": 37, "creator_user_id": ...}` from `ChatInviteExported`.
- **Matrix permalink**: `{"via_servers": ["matrix.org", "example.com"]}` — required to actually federate the join.
- **WhatsApp invite v3**: `{"chat_jid": "...", "inviter_jid": "...", "invite_code_revision": 4}`.
- **Discord invite**: `{"vanity": true|false, "guild_id": "...", "channel_id": "...", "approximate_member_count": ...}`.
- **IRC channel modes**: `{"modes": "+nt", "requires_key": false, "requires_invite": false}`.

**Supervisor selection at join time** (extends §2.20 state machine):
```
1. SELECT artifacts WHERE candidate_id = X
   AND validation_state IN ('valid', 'unverified')
   AND requires_admin_approval = FALSE
   ORDER BY kind_preference ASC, last_validated_at DESC LIMIT 1
2. kind_preference: public_identifier=1, invite_link=2, qr_code=3,
                    direct_invite=4, paid_subscription=5, restricted_other=6
   (cheapest, lowest-OPSEC-cost, most-stable first)
3. If candidate is unverified, supervisor RE-VALIDATES before issuing JoinGroupCommand;
   on success, writes valid + last_validated_at and proceeds.
4. If all artifacts exhausted (none valid after re-validation) →
   candidate.failed, last_error_type="NoValidAccessArtifact",
   collector remains healthy.
```

**Why `value` allows null:** `direct_invite` and `access_blocked` are KNOWN access states with no transferable token. We still want a row to record "this group exists, we discovered it, and the only way in is to be invited by an existing member" — that's an operator-actionable state (the operator can task an actor relationship to obtain an invite).

**`Group.is_public: bool | None`** (§1.3) stays as the abstract platform property: "can a stranger join at all?" The artifact table is the operational truth: "by what mechanism, with what current validity, from which of our identities."

### 2.25 Cross-source bridge resolution — system invariant, NOT a tool

When a domain-shaped `InfrastructureArtifact` (§2.7) matches a configured Source's `base_url`, the system must populate `resolved_to_source_id` automatically — **inside the same transaction as the triggering write**. Operators do not run resolution jobs. The system is responsible for keeping the bridge state consistent at all times.

This is enforced as a **storage-layer invariant**, declared on `SQLModelRepository` (the generic mixin, no dialect leak per CLAUDE.md §2.3 Rule 1). Two trigger paths:

**Path A — artifact written:**
```python
# Pseudocode — eyenet/storage/sqlmodel_repo/infrastructure.py
async def put_infrastructure_artifact(self, art: InfrastructureArtifact) -> InfrastructureArtifact:
    # ... normal insert/upsert ...
    if art.kind in BRIDGEABLE_KINDS:                       # domain, onion, paste_url
        matches = await self._find_sources_for_artifact(art)
        if len(matches) == 0:
            art.resolution_state = ResolutionState.UNRESOLVED
        elif len(matches) == 1:
            art.resolved_to_source_id = matches[0].id
            art.resolution_state = ResolutionState.RESOLVED
            await self._emit_audit("infrastructure.resolved_on_ingest", ...)
        else:
            art.resolution_state = ResolutionState.AMBIGUOUS
            await self._emit_audit("infrastructure.ambiguous_on_ingest", ...)
    elif art.kind in NOT_APPLICABLE_KINDS:                 # wallets, pgp, email, phone
        art.resolution_state = ResolutionState.NOT_APPLICABLE
    # ...
```

**Path B — Source created or its `base_url` changed:**
```python
# Pseudocode — eyenet/storage/sqlmodel_repo/sources.py
async def create_source(self, source: Source) -> Source:
    # ... insert Source ...
    affected = await self._resolve_existing_artifacts_for_source(source)
    # affected = (resolved_count, newly_ambiguous_count, was_pending_count)
    if affected.resolved_count > 0:
        await self._emit_audit(
            "source.bridge_resolved_existing_artifacts",
            payload={"source_id": source.id, **asdict(affected)},
        )
    return source

async def update_source_base_url(self, source_id: UUID, new_base_url: str) -> Source:
    # ... update ...
    # MUST also re-run resolution for both:
    #   (a) artifacts that were resolved to this source under the old base_url
    #       (may now be wrong → re-evaluate)
    #   (b) artifacts that were unresolved/ambiguous (may now match)
    ...
```

**Matching predicate** (`_find_sources_for_artifact`) — driven by `SourceDomain` rows (§2.26), NOT by `Source.canonical_url`:
- Normalize artifact `value` to a bare hostname via the canonical helper `eyenet.util.domain.normalize_host` (§2.26 "Hostname normalization" — lowercase, strip `www.`, strip port, strip scheme/path if `paste_url`, **punycode-encode IDN labels**). Both sides of every comparison MUST go through the same helper.
- Query `SourceDomain` in specificity order:
  1. `pattern_kind = 'exact'` AND `pattern = host`
  2. `pattern_kind = 'subdomain_wildcard'` AND host's parent-domain matches the wildcard's base (`pattern = "*.example.com"` matches `sub.example.com` but not `example.com` itself)
  3. `pattern_kind = 'suffix_match'` AND `host` ends with the pattern's suffix
- Higher-specificity hits SHADOW lower-specificity hits: if `forum.example.com` matches both an `exact` pattern on Source A AND a `subdomain_wildcard` pattern on Source B, only Source A is returned. This prevents wildcard Sources from accidentally claiming hostnames another Source explicitly owns.
- For `kind = "onion"`: same algorithm restricted to `SourceDomain` rows where `onion = TRUE`.

Sources with no `SourceDomain` rows (Telegram, Matrix, IRC) are excluded from the matching set — they cannot bridge a domain artifact, because they have no domains.

**Ambiguity handling.** Two operator-configured Sources both matching the same domain is an operator mistake (two MyBB Sources for the same forum?) but the system handles it gracefully: `resolution_state = ambiguous`, FK stays null, audit row written. The operator UI surfaces these for manual resolution. **The system never picks one arbitrarily.**

**Re-resolution on Source mutation.** Changing `Source.base_url` (rare but legal — operator corrects a typo, or the platform's host migrates) triggers a full re-evaluation of artifacts previously resolved to that Source AND of artifacts that may now newly match. Audit events `infrastructure.resolution_revoked` and `infrastructure.resolved_post_source_change` track the deltas. This is the one place where an UPDATE-triggered job touches multiple artifact rows — bounded by "artifacts pointing at this Source" + "artifacts whose value matches the new base_url hostname". For a typical operator, both sets are small.

**What this is NOT:**
- ❌ Not a periodic background job. The operator does not run `tools/resolve_artifacts.py`. There is no `tools/resolve_artifacts.py`. The invariant is enforced inline by the write that creates the asymmetry.
- ❌ Not a queue. There is no "pending resolution" state outside `unresolved`/`ambiguous`. Either the system resolved it at write time or there was nothing to resolve to.
- ❌ Not a notification system. Resolution writes audit rows and SystemLog entries; the UI subscribes to those streams (existing pattern). No new SSE subject for bridge events alone — too noisy for its own feed.

**Operator experience.** Operator configures `Source(kind="forum", base_url="https://forum.example.com", ...)`. In the same transaction, every previously-unresolved `InfrastructureArtifact` for `forum.example.com` gets `resolved_to_source_id` populated. Operator opens the new Source's detail page; sees "47 actors mentioned this domain across 213 messages BEFORE this source was configured" — instantly. No script run. No "click to scan."

**Edge case: artifact created BEFORE matching Source exists, no operator action between.** The first write (the artifact) goes `unresolved`. The second write (the Source) triggers Path B and resolves it. Two audit rows; one resolution; correct end state. No race because both writes are serialized by SQLite's single-writer model and within their own transactions.

**Edge case: Source deleted while artifacts point to it.** Storage-layer FK behavior: ON DELETE SET NULL on `resolved_to_source_id`, AND a trigger writes back `resolution_state = unresolved` for affected rows. Audit event `infrastructure.unresolved_post_source_delete` per row. (For SQLite this is enforced by a transactional pre-delete sweep in `delete_source`, not by SQL triggers — keeps the logic in one place.)

### 2.26 `SourceDomain`
The hostname/pattern set a web-based `Source` owns. **One `Source` → many `SourceDomain` rows.** First-class, indexed, queryable. Not a JSON column on Source — the bridge resolver (§2.25) needs reverse-lookup performance from day one, and JSON in SQLite doesn't index sensibly for that.

Models forum mirrors, archive subdomains, CDN edges, onion alternates, and platform migrations — all the cases where "this Source has more than one valid hostname" actually happens in practice.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `source_id` | FK → Source | |
| `pattern` | str | normalized lowercase hostname or pattern; never includes scheme, port, or path |
| `pattern_kind` | enum | `exact` (e.g. `forum.example.com`), `subdomain_wildcard` (e.g. `*.example.com` — matches ANY subdomain but NOT the apex), `suffix_match` (e.g. `.example.org` — matches any host ending in this suffix; use sparingly, broadest reach) |
| `is_primary` | bool | exactly one TRUE per Source — the canonical pattern shown in the operator UI's source picker, used for human-readable references in audit/log payloads |
| `is_onion` | bool | TRUE for `.onion` patterns; bridge resolver only matches `kind="onion"` artifacts against `is_onion=TRUE` rows, and only matches `kind="domain"` artifacts against `is_onion=FALSE` rows |
| `added_at` | datetime | |
| `added_by` | FK → SystemUser | who added this domain to the Source |
| `removed_at` | datetime \| None | soft-delete; row is retained for audit. Removed rows are excluded from matching but stay queryable |
| `notes` | str \| None | "added during platform migration 2026-06"; operator scratchpad |

**Indexes:**
- `(pattern, pattern_kind)` UNIQUE WHERE `removed_at IS NULL` — same active pattern with same kind cannot exist twice. Two Sources cannot both own the exact pattern `forum.example.com`. Soft-deleted rows are excluded so a removed pattern can be re-added (or re-claimed by another Source) cleanly.
- `(source_id, is_primary)` UNIQUE WHERE `removed_at IS NULL AND is_primary = TRUE` — enforces "exactly one primary per Source" at the DB level, not just by convention.
- `(pattern_kind, pattern)` plain index — the bridge resolver's hot-path query.
- `(is_onion, pattern_kind, pattern)` partial — onion lookups are a hot path for hidden-service-centric investigations.

**Constraint:** `is_primary = TRUE` implies `pattern_kind = 'exact'` and `removed_at IS NULL` — the canonical pattern must be a specific hostname, not a wildcard, and must be active. Enforced by CHECK constraint.

**Overlap detection — refuse at write time.**

When `add_source_domain(source_id, pattern, pattern_kind, ...)` is called, the storage layer runs a conflict scan **before** the INSERT commits:

```python
# Pseudocode — eyenet/storage/sqlmodel_repo/source_domains.py
async def add_source_domain(self, ...) -> SourceDomain:
    overlaps = await self._scan_overlaps(pattern, pattern_kind)
    # overlaps = [(other_source_domain, other_source_id, why_overlap), ...]
    foreign = [o for o in overlaps if o.other_source_id != source_id]
    if foreign:
        if not force:
            raise SourceDomainOverlap(
                pattern=pattern,
                conflicts=[(o.other_source_id, o.other_pattern, o.why_overlap) for o in foreign],
            )
        # operator forced — mark BOTH sides ambiguous in the bridge resolver,
        # and write a loud audit event
        await self._mark_ambiguous_for_overlap(...)
        await self._emit_audit("source_domain.overlap_forced", payload={...})
    # commit insert
```

`_scan_overlaps` checks:
- `pattern_kind = 'exact'` against existing exact matches AND wildcards whose base it falls under AND suffixes it ends with
- `pattern_kind = 'subdomain_wildcard'` against existing wildcards/suffixes that would share the subdomain space
- `pattern_kind = 'suffix_match'` against existing suffixes that overlap, and exacts/wildcards that fall under it

The operator gets a clear error at config time:

```
SourceDomainOverlap: pattern 'forum.example.com' (exact) for Source 'Example Forum'
conflicts with existing pattern '*.example.com' (subdomain_wildcard) owned by Source 'Example Network'.
Use --force to add anyway (BOTH sources will be marked ambiguous for hostnames in the overlap).
```

This is the gate against the silently-ambiguous-Source problem: you find out at `eyenet source domain add` time, not three weeks later when a candidate fails to resolve.

**Migrations / mirror moves.** When a forum migrates from `forum.example.com` to `community.example.com`, the operator runs:
```
eyenet source domain add <source_id> community.example.com --kind exact
eyenet source domain remove <source_id> forum.example.com --keep-history
```
The removed row stays in the table with `removed_at` populated; historical `InfrastructureArtifact` rows that resolved to `forum.example.com` via the old row keep their FK intact (the FK points at `Source`, not at `SourceDomain`). New artifacts mentioning the old domain now go `unresolved` per §2.25 — which is correct, because the platform no longer claims it. If the operator wants the old domain to keep resolving (cache, partial mirror still up), they re-add it.

**Why an enum-of-three instead of full regex / glob:** because regex/glob patterns are a footgun in a security context. `*.example.com` and `.example.com` and `forum.example.com` cover every real case I have ever observed in 25 years. If you find yourself wanting regex, you almost certainly want a second SourceDomain row, not a regex.

#### Hostname normalization — canonical helper, single source of truth

Every hostname that crosses the storage boundary — `SourceDomain.pattern`, `InfrastructureArtifact.value` (for `kind ∈ {domain, onion, paste_url}`), the `host` derived from `Source.canonical_url`, and every value used in matching queries — passes through a single helper:

```python
# eyenet/util/domain.py
from idna import encode as _idna_encode, IDNAError
from urllib.parse import urlparse

_WWW_PREFIX = "www."

def normalize_host(raw: str, *, allow_wildcard: bool = False) -> str:
    """
    Canonical hostname normalization for storage and matching.

    Rules (applied in order):
      1. If 'raw' parses as a URL (has scheme://), extract the hostname; else treat 'raw'
         as a bare host candidate.
      2. Strip surrounding whitespace and the trailing dot (FQDN root).
      3. Lowercase ASCII.
      4. Strip a leading 'www.' (only the first; 'www.www.example.com' loses ONE 'www.').
      5. If 'allow_wildcard' AND the host starts with '*.':
            - normalize the remainder (recursive call with allow_wildcard=False)
            - re-prefix with '*.'
         Else if the host contains '*' anywhere: raise InvalidHostnameError.
      6. Punycode-encode (IDNA 2008) each label. ASCII labels pass through unchanged;
         non-ASCII labels become 'xn--...'. The empty string and pure-ASCII inputs are
         a no-op. IDNAError → raise InvalidHostnameError with the offending label.
      7. Validate final result is a syntactically valid hostname (LDH per label,
         no length > 253 total, no label > 63). Raise InvalidHostnameError on failure.
    """
    ...
```

**Every caller uses this helper.** No inline `.lower()`. No inline `urlparse(...).hostname`. No inline `idna.encode`. If you find a hostname being touched without `normalize_host`, fix it — the file you found it in is wrong.

Why centralized:
- IDN ambiguity is THE classic homograph attack vector. `аррӏе.com` (Cyrillic) and `apple.com` (ASCII) render identically in many fonts; they must be stored differently and matched only against their own normalized forms. The helper guarantees `аррӏе.com` becomes `xn--80ak6aa92e.com` BEFORE storage, BEFORE matching, BEFORE comparison.
- A SourceDomain pattern stored as `forum.example.com` and an InfrastructureArtifact value stored as `Forum.Example.com.` (trailing dot, mixed case) must match. Inconsistent normalization is silent resolution failure, and silent resolution failure is the worst kind of bug in an intelligence system — you have the data, you just can't find it.
- Wildcard handling (`*.example.com`) requires a discriminator parameter so accidental wildcards in artifact values (`*.evil.com` mentioned in a message) raise instead of being silently stored.

**Test fixture rule** (worth saying out loud): tests that exercise the bridge resolver MUST include at least one IDN host and at least one mixed-case input. The default fixture set in `tests/_seed.py` will ship with these. If a future change to `normalize_host` regresses on punycode, the test suite fails immediately, not on an operator three months later.

**`Source.canonical_url` validation hook.**

`canonical_url`'s constraint (§1.1) is enforced via:

```python
# Pseudocode — eyenet/storage/sqlmodel_repo/sources.py
async def _validate_canonical_url(self, source: Source) -> None:
    if source.canonical_url is None:
        return
    parsed = urlparse(source.canonical_url)
    if not parsed.scheme or not parsed.hostname:
        raise InvalidCanonicalURL(reason="must be a full URL with scheme + host")
    host = normalize_host(parsed.hostname)
    primary = await self._get_primary_domain(source.id)
    if primary is None:
        raise InvalidCanonicalURL(reason="source has no primary SourceDomain; add one before setting canonical_url")
    if primary.pattern_kind != PatternKind.EXACT:
        # Defensive — the is_primary CHECK already enforces this.
        raise InvalidCanonicalURL(reason="primary SourceDomain must be pattern_kind='exact'")
    if host != primary.pattern:
        raise InvalidCanonicalURL(
            reason=f"canonical_url host '{host}' does not match primary SourceDomain pattern '{primary.pattern}'",
        )
```

Invoked from `create_source`, `update_source`, AND `set_primary_source_domain` (because primary swaps can invalidate a canonical_url that was valid yesterday — the set-primary path must either reject the swap or null-out the canonical_url, operator's call via a `--update-canonical-url` flag).

### 2.27 Discovery-driving sensor primitives — what feeds §2.20–§2.21 and §2.7

The model rows in this document don't appear out of nowhere — the sensor layer's discovery primitives produce them on every Message. Two are first-class for the discovery loop and the cross-source bridge; both are platform-agnostic and live in `eyenet/sensor/primitives/discovery/`.

#### `channel_reference_extraction` — feeds `GroupCandidate` + `GroupCandidateMention`

Runs on every Message. For each detected reference to a group EYENET doesn't already observe:

- **Detection rules (per Source kind):**
  - Telegram: `@username` tokens (validate via Telethon `get_entity` is a `Channel` or `Chat`), `t.me/<X>` URLs, `t.me/+<X>` / `t.me/joinchat/<X>` invite links, `forward_from_chat` headers on forwarded messages, link-preview `webpage.channel` entities, QR codes in attachments (if attachment OCR is enabled — defer).
  - Matrix: `#alias:server` mentions in `m.text` bodies, `matrix.to/#/!roomid?via=...` URLs, `m.room.member` events for rooms the collector isn't in but is told about via federation gossip.
  - IRC: `#channel` tokens in PRIVMSG bodies, `INVITE` events for channels not in `JOIN` state.
  - Forum / web (future): `<a href="...">` to threads/categories on the same or another forum platform.
- **Resolve-before-emit:** every detected token MUST be platform-resolved (Telethon `get_entity`, Matrix `/_matrix/client/v3/directory/room/{alias}`, etc.) before a `GroupCandidateMention` is written. Garbage mentions inflate scores; an unresolved `@channel_that_doesnt_exist` is noise, not signal.
- **Output:** upsert `GroupCandidate` (by `(source_id, platform_groupid)`); INSERT `GroupCandidateMention` with `mention_kind`, `seed_root_id` (walked from the collector's current root membership chain), `depth_from_root` (incremented from the observing group's depth + 1), `mentioning_actor_id`, `mentioning_actor_role_signal` (snapshot from `Profile.role_signal` at write time).
- **Same-source filter:** the primitive ONLY emits mentions for the SAME Source as the observing message. A Telegram message mentioning a Matrix room is handled by `url_extraction` below, not here. Discovery loops are intra-source by design.

#### `url_extraction` — feeds `InfrastructureArtifact` + `ActorArtifact`

Runs on every Message regardless of source. The cross-source intelligence log.

- **Detection rules (platform-agnostic):**
  - URL extraction via a strict parser (`urllib.parse` post-validated; NOT regex). Skip `t.me/*`, `matrix.to/*`, `discord.gg/*`, and other source-internal URL schemes — those are `channel_reference_extraction`'s territory.
  - Bare-domain extraction (text containing `forum.example.com` without scheme) via a conservative pattern: requires at least one dot, a valid TLD per the IANA list, AND surrounding-token context indicating "this looks like a domain reference" (e.g., preceded by `http`, `://`, whitespace, line start; followed by whitespace, punctuation, line end). Single-pass false-positive-leaning: prefer to miss ambiguous mentions over generating noise.
  - Onion address pattern: `[a-z2-7]{16}\.onion` (v2, deprecated upstream but still occurs in old data) or `[a-z2-7]{56}\.onion` (v3).
  - Pastebin URLs (pastebin.com, ghostbin, etc.) — extracted as `kind=paste_url`. Operator may configure additional pastebin patterns via `Source` configuration when the pastebin itself is a configured Source.
  - Bitcoin / Monero / Ethereum addresses via the canonical regex + checksum validation. Failed-checksum hits are dropped (they're not real addresses).
  - Email addresses, phone numbers — extracted with conservative patterns to avoid false positives on numeric IDs.
  - PGP key blocks — detect `-----BEGIN PGP PUBLIC KEY BLOCK-----` markers, extract the key fingerprint, normalize to `value`.
- **Normalization:** every detected domain/onion/URL passes through `normalize_host` (§2.26) before storage. Wallets through the canonical address-normalization helper per kind. Phones through E.164 normalization. Emails through RFC-5321-compliant local + normalized-host.
- **Output:** upsert `InfrastructureArtifact` keyed by `(kind, value_hash)`. INSERT `ActorArtifact(actor_id=message.actor_id, artifact_id, first_seen_evidence_ref=message.evidence_ref, confidence=...)` with default `confidence = 1.0` for first-party observation, lowered for forwarded content where attribution is ambiguous.
- **Bridge resolution:** the upsert path in storage automatically resolves `domain` / `onion` / `paste_url` artifacts against `SourceDomain` rows per §2.25, in-transaction. The sensor primitive does NOT call bridge resolution itself — it just writes the artifact and lets the storage layer's invariant fire.

**Why these are in §2 (the model layer) and not just sensor-layer concerns:** because the model rows they produce are the substrate every other section depends on. `GroupCandidate` is meaningless without a primitive that creates rows. `InfrastructureArtifact` is just an empty table without `url_extraction`. The model doc is where the contract between primitives and rows is anchored — implementation lives in `eyenet/sensor/primitives/discovery/`, but the SHAPE is here.

**Versioning.** Both primitives carry `primitive_version` per the existing Observation convention. A version bump invalidates downstream score recomputation (§4.12.2's `score_function_version` bumps in lock-step). Operators see the version in the audit payload of every emitted row — so when you change `channel_reference_extraction` v0.3 → v0.4 to add Discord invite-link support, every candidate-mention from v0.4 onward carries that version stamp, and the operator can filter "show me only post-Discord-support mentions."

### Extensions to existing models

**`Case` (§2.17) gains:**

| Field | Type | Notes |
|---|---|---|
| `redundancy_policy` | enum | `prefer_single` (default — skip if any collector is already in the group), `prefer_dual` (allow second collector when bandwidth permits), `required_dual` (refuse to operate with single coverage — alerts on degradation) |
| `auto_join_policy` | enum | `disabled` (every candidate is operator-triaged), `score_threshold` (auto-approve when `GroupCandidate.score ≥ threshold`), `score_threshold_with_role_gate` (auto-approve only when the mentioning actor has `role_signal ∈ {credential_broker, group_admin, ...}` AND score crosses threshold) |
| `auto_join_score_threshold` | float \| None | applied when `auto_join_policy ≠ disabled` |
| `seed_root_group_ids` | list[UUID] (JSON) | the operator-curated initial root set for this case; depth-0 in the discovery tree. Mutating this list emits `case.seed_roots_changed`. |

**`Source` (§1.1) gains:**

| Field | Type | Notes |
|---|---|---|
| `default_redundancy_policy` | enum | source-wide default applied to groups not scoped to any Case; per-Case policy overrides |
| `default_auto_join_policy` | enum | same |

**`Identity` (§2.1) gains:**

| Field | Type | Notes |
|---|---|---|
| `role` | `IdentityRole` enum | `monitor`, `scout`, `quarantine` — see §2.19 extension. Default `monitor`. Supervisor uses `scout` identities for first joins of new candidates; graduates to `monitor` after the observation window. |
| `graduated_at` | datetime \| None | when a scout identity graduated to monitor; null for born-monitor identities |

**`Group` (§1.3) gains:**

| Field | Type | Notes |
|---|---|---|
| `discovered_via_candidate_id` | UUID \| None FK GroupCandidate | populated when this Group was created from an approved-then-joined candidate; null for operator-seeded groups |

---

## 3. Polymorphism call

Telegram, Matrix, IRC, forums diverge in ways that don't deserve their own tables. **Decision (proposed):** single `Message` (and `Group`) tables with a `source_specific: dict` JSON column. Common fields stay typed; weird platform stuff goes in JSON. Reverse decision only if a per-source query gets slow enough to need indexed columns we lack.

---

## 4. Bus envelopes vs DB rows

These are **NOT** the same models:

| Concern | Bus envelope | DB row |
|---|---|---|
| `Observation` | `decnet_behave_text.spec.Observation` (imported) | §2.3 above |
| `RawMessage` | thin envelope: `evidence_ref` + minimal metadata | §1.4 (full body retained server-side) |
| `ProfileCurrent` | snapshot summary | §2.4 |
| `LinkageProposed` | snapshot of proposal | §2.5 row in `state=proposed` |

Bus envelopes are **transport optimizations** for high-fanout subjects. DB rows are **the operator's evidence**. They share IDs and `evidence_ref`s; they do not share schemas.

---

## 5. Open questions

1. **Profile representation** — snapshot vs event-sourced (already PLAN §11.2). Above sketch is snapshot.
2. **Persona vs Linkage redundancy** — should `Persona.member_actor_ids` be denormalized (cheap reads, rebuildable) or computed (linkage graph traversal at query time)? Lean denormalized.
3. **`source_specific` schemas** — do we lock per-source JSON schemas (Pydantic discriminated unions on `source.kind`) or accept free-form? Lean discriminated unions, validated, but with a permissive pass-through field for unmodeled platform extras.
4. **`Attachment` retention policy** — by default, do we download attachments or only metadata? Default OFF (privacy + storage); per-Case opt-in.
5. **Soft-delete / right-to-be-forgotten** — operator-initiated only; cascade behavior to Profile/Linkage/Persona is non-trivial. Defer to its own design pass.

---

## 6. What I deliberately did NOT model (yet)

- **Threat indicators / IOCs as first-class** — `InfrastructureArtifact` covers wallets/domains, but full IOC taxonomy (CVE refs, malware family, attack pattern) is its own subsystem. Defer.
- **Notifications / alerts** — out of v0 scope.
- **Graph node/edge tables** — the Graph service's internal representation. Lives behind its own abstract factory; not part of the shared model layer.
