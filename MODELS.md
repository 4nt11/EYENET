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
A specific origin. **Telegram has one Source row; each forum domain is its own Source row.** Distinct from `SourceKind` (the enum).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `kind` | `SourceKind` enum | `telegram`, `matrix`, `irc`, `discord`, `forum`, `rss`, `xmpp`, ... |
| `display_name` | str | "Telegram", "forum.example.com" |
| `base_url` | str \| None | for forums/web sources |
| `created_at` | datetime | |
| `notes` | str \| None | operator scratchpad |

**Important:** `Source` does NOT carry credentials. Credentials = `Identity` (§2.1).

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
| `value_kind` | enum | `hash`, `numeric`, `enum_str`, `array_str` |
| `value_hash` | str \| None | for `hash` kind |
| `value_numeric` | float \| None | |
| `value_enum` | str \| None | |
| `value_array` | list[str] \| None | as JSON |
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
| `actor_a_id` / `actor_b_id` | FK | unordered; enforce `a < b` to dedupe |
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
| `member_actor_ids` | list[UUID] | denormalized; rebuildable from linkages |
| `created_at` / `updated_at` | datetime | |

### 2.7 `InfrastructureArtifact`
Wallets, PGP keys, domains, phone numbers, emails, cross-platform handles, onion addresses. The Actor↔Infrastructure relation in the goals.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `kind` | enum | `wallet_btc`, `wallet_xmr`, `wallet_eth`, `pgp_key`, `domain`, `onion`, `email`, `phone`, `handle_other_platform`, `paste_url` |
| `value` | str | normalized form |
| `value_hash` | str index | `sha256(value)` for fast lookup |
| `first_seen_at_ingest` | datetime | |
| `last_seen_at_ingest` | datetime | |

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
| `actor_id` \| `group_id` | FK (one of) | |
| `authorized_by` | str | |
| `authorized_at` | datetime | |
| `scope` | enum | `observe_only`, `passive_engage`, `active_engage` |
| `expires_at` | datetime \| None | |

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

### 2.17 `SystemUser`
The operator(s) of EYENET itself. Multi-user is now in scope — this **conflicts with PLAN.md §12 ("No multi-tenant operator separation")** which needs to be relaxed accordingly. v0 ships with single-user-default but the model supports N from the start (per the "design plural from day one" principle).

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

### 2.18 `SystemLog`
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

### 2.15 `Case`
Operator's investigation grouping. Drives hot/cold/archived tier transitions per §5.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | str | "Rutify-Q2-2026" |
| `state` | enum | `open`, `closed`, `archived` |
| `opened_at` / `closed_at` | datetime | |
| `actor_ids` / `group_ids` | list[UUID] | scope of the case |
| `notes` | str | |

### 2.16 Internal: `CorpusCursor`
Sensor's bookmark per actor. Not exposed; here so it isn't forgotten.

| Field | Type | Notes |
|---|---|---|
| `actor_id` | FK PK | |
| `primitive_name` | str | composite PK with actor_id |
| `last_processed_msg_ts` | datetime | |
| `last_processed_msg_id` | UUID | |

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
- **Operator users / RBAC** — single-operator assumption in v0 (PLAN §12 non-goals).
- **Notifications / alerts** — out of v0 scope.
- **Graph node/edge tables** — the Graph service's internal representation. Lives behind its own abstract factory; not part of the shared model layer.
