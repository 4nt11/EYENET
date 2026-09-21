# EYENET API_PLAN.md

**Status:** Draft — 2026-05-24
**Supersedes:** `eyenet/query_api/` (toy; kept running until v1 reaches parity, then deleted)
**Owners:** ANTI (impl) · Dr. Ragesworth (architecture review)
**Cross-refs:** `PLAN.md` (system), `MODELS.md` §2.17 (SystemUser), `TESTING.md` (test policy)

---

## 0. Why this exists

`eyenet/query_api/` was a 250-LOC read-only smoke test of "can we serve graph reads over HTTP." It proved the wiring. It did not address:

- **Authentication.** None.
- **Authorization.** None.
- **Audit emission on read.** None — direct violation of `PLAN.md` §152 (every dereference outside the producing Sensor MUST emit `eyenet.audit.evidence_access`).
- **Writes.** None — operator decisions are CLI-only today.
- **Realtime.** None — UIs that want bus events have nowhere to subscribe.
- **Versioning.** None — routes live at `/actor/...`, no prefix, first breaking change forces a flag day.
- **Pagination semantics.** Offset/limit only, no totals, no cursors.
- **Typed query params.** `state: str | None` instead of enums; garbage params return `[]` silently.
- **Error contract.** Default FastAPI error envelope, no `request_id`, no problem+json.

The real API is a first-class subsystem with the same operator-grade-evidence posture as the rest of EYENET: every read is audited, every write goes through the bus (single source of truth), every operator action is attributable to a `SystemUser`.

---

## 1. Consumers, in priority order

| Consumer | Auth | Posture |
|---|---|---|
| **Operator UI** (future web/TUI client) | JWT (access + refresh), short-lived | Human-in-the-loop; needs SSE for live linkage proposals; needs login/logout. |
| **External integrators** (SIEM exporters, partner tooling, scripts) | Personal Access Tokens (PATs) — long-lived, hashed at rest | Programmatic; same scope/permission model as JWTs; no refresh flow. |

**Explicit non-consumers (v1):**

- Sister EYENET services (Engine, Linker, Graph, Confirmer, Verifier) — they talk over NATS, not HTTP. The bus stays the bus. We do not add a second control plane.
- Public internet. Not in v1. The API may bind to a non-localhost interface, but the trust boundary is the operator's network. No anonymous endpoints; no rate-limited public reads.

---

## 2. Posture / invariants

These are non-negotiable. Every endpoint, every middleware, every test reads back to one of these.

1. **Audit-equivalent to CLI.** Every read that dereferences evidence emits `eyenet.audit.evidence_access`. Every write emits `eyenet.audit.operator_action`. Auth events emit `eyenet.audit.auth`. The hash chain stays linear and unbroken.
2. **Writes are bus events, not DB writes.** The API publishes to NATS (e.g. `attribution.linkage.confirmed`) and the Graph service applies them. The API does not bypass the bus. Same code path operator-CLI writes already take.
3. **Operator-grade retention.** No content minimization at the API. If the operator has permission to see it, they get the full row.
4. **No silent failures.** Unknown query param → 422. Unknown enum value → 422. Missing permission → 403. Missing auth → 401. Default 500 envelope is treated as a bug.
5. **Versioned.** Every route lives under `/v1/`. Pydantic schemas live in a versioned package. Breaking changes require `/v2/`.
6. **Idempotent writes.** Every write endpoint accepts `Idempotency-Key` (RFC-like). Replays of the same key return the original response without re-emitting bus events.
7. **Storage stays typed.** No `cast()` in route handlers. Storage methods declare concrete return types.

---

## 3. Surface map

Six resource groups, all under `/v1/`.

### 3.1 Auth (`/v1/auth/`)

| Method | Path | Purpose | Permissions |
|---|---|---|---|
| POST | `/login` | username + password → access JWT + refresh token | public |
| POST | `/refresh` | refresh → new access JWT | refresh token in body |
| POST | `/logout` | revoke refresh + denylist current access jti | authenticated |
| GET | `/me` | current `SystemUser` + scopes | authenticated |
| GET | `/tokens` | list this user's active PATs | authenticated |
| POST | `/tokens` | mint a new PAT (returns secret ONCE) | `admin:tokens` or self |
| DELETE | `/tokens/{token_id}` | revoke a PAT | self or `admin:tokens` |

### 3.2 Reads — actors / personas / linkages

| Method | Path | Permissions | Audit emission |
|---|---|---|---|
| GET | `/actors/{actor_id}` | `read:actors` | `evidence_access(actor)` |
| GET | `/actors/{actor_id}/neighbors` | `read:actors` | `evidence_access(actor)` |
| GET | `/actors/{actor_id}/observations` | `read:observations` | `evidence_access(observation)` per row |
| GET | `/actors/{actor_id}/timeline` | `read:observations` | `evidence_access(observation)` per row |
| GET | `/personas/{persona_id}` | `read:personas` | `evidence_access(persona)` |
| GET | `/personas/{persona_id}/members` | `read:personas` | `evidence_access(persona)` |
| GET | `/linkages` | `read:linkages` | none (index read, no dereference) |
| GET | `/linkages/{linkage_id}` | `read:linkages` | `evidence_access(linkage)` + comparator evidence |
| GET | `/graph/stats` | `read:graph` | none (aggregate counts) |
| GET | `/graph/search?q=...` | `read:actors` | `evidence_access` per returned actor |

### 3.3 Audit (`/v1/audit/`)

| Method | Path | Permissions |
|---|---|---|
| GET | `/audit?since=&until=&user=&subject=&cursor=` | `read:audit` |
| GET | `/audit/verify` | `read:audit` — recomputes hash chain, returns first break |

Reading the audit log does NOT emit a new audit row (avoids infinite recursion). It is logged separately at telemetry level only.

### 3.4 Writes — operator decisions

All writes accept `Idempotency-Key` header; all writes publish to the bus, return 202 + the resulting subject/event id; the API never mutates storage directly.

| Method | Path | Permissions | Bus subject |
|---|---|---|---|
| POST | `/linkages/{linkage_id}/confirm` | `write:linkage_decision` | `attribution.linkage.confirmed` |
| POST | `/linkages/{linkage_id}/reject` | `write:linkage_decision` | `attribution.linkage.rejected` |
| POST | `/linkages/{linkage_id}/suspect` | `write:linkage_decision` | `attribution.linkage.suspected` |
| POST | `/identities/{identity_id}/claim` | `write:identity` | `eyenet.identity.claimed` |
| POST | `/identities/{identity_id}/release` | `write:identity` | `eyenet.identity.released` |
| POST | `/identities/{identity_id}/freeze` | `write:identity` | `eyenet.identity.frozen` |
| POST | `/identities/{identity_id}/burn` | `write:identity` | `eyenet.identity.burned` |
| POST | `/identities/freeze_all` | `write:identity` | `eyenet.identity.freeze_all` |
| POST | `/personas/{persona_id}/merge` | `write:persona_decision` | `attribution.persona.merge` |
| POST | `/personas/{persona_id}/split` | `write:persona_decision` | `attribution.persona.split` |
| POST | `/panic` | `write:panic` | `eyenet.control.panic` (global) |

**Identity verb set (reconciliation).** This table is authoritative:
`claim / release / freeze / burn / freeze_all`. The M9.G5 milestone text below
(§ Group G) originally read "freeze | burn | release" while §3.4 read
"claim / release / freeze_all" — a contradiction resolved 2026-09-21 toward the
operational superset. `freeze` (per-identity soft freeze) and `burn` (permanent
retirement of a compromised identity) are first-class operator actions;
`freeze_all` is the fleet-wide soft freeze. All are gated by `write:identity`.

**Persona merge/split** are operator overrides of the automatic persona merge
Graph performs on a confirmed linkage. Their action model — request bodies,
lifecycle, applier — is §4.10a below. Gated by the new `write:persona_decision`
scope (admin + analyst baseline, mirrors `write:linkage_decision`).

### 3.5 Realtime (`/v1/stream/`)

Server-Sent Events. One endpoint per topic family, plus a multiplexed catch-all for the UI.

| Method | Path | Permissions | Backing subject(s) |
|---|---|---|---|
| GET | `/stream/linkages` | `stream:linkages` + `read:linkages` | `attribution.linkage.*` |
| GET | `/stream/personas` | `stream:personas` + `read:personas` | `attribution.persona.updated` |
| GET | `/stream/audit` | `stream:audit` + `read:audit` | `eyenet.audit.*` |
| GET | `/stream/control` | `stream:control` + `read:audit` | `eyenet.control.*`, `eyenet.identity.freeze_all`, `eyenet.identity.released` |
| GET | `/stream/all?topic=...&topic=...` | union of above | filtered fan-out |

The `control` stream surfaces panic, global freeze, and other system-wide operator actions so the UI can react in realtime (banners, mode locks, audit emphasis). It is gated by `stream:control` (a new scope, listed in §4.4) plus `read:audit` because the control envelope payload is intentionally minimal — full forensic detail is in the audit chain.

### 3.6 Health

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | process up. No auth. |
| GET | `/readyz` | storage open + bus subscribed + auth keys loaded. No auth. |
| GET | `/v1/metrics` | Prometheus scrape (when enabled). `read:metrics` scope. See §11.7. |

The same readiness signals are mirrored as Prometheus gauges (`eyenet_api_healthy`, `eyenet_api_ready{component=...}`, see §11.7.2) so ops teams running Prometheus do not need a separate Blackbox-exporter probe.

### 3.7 Collectors (`/v1/collectors/`)

The runtime fleet — the only place the UI can spin up, configure, start, stop, or inspect a live collector. See §4.11 for the full lifecycle/auth/supervisor contract.

| Method | Path | Purpose | Scope |
|---|---|---|---|
| GET | `/v1/collectors` | list fleet — paginated; redacted `config` for viewers | `read:collectors` |
| GET | `/v1/collectors/{id}` | single collector — full config requires `read:collectors_config` | `read:collectors` |
| POST | `/v1/collectors` | create — body validated by Pydantic discriminated union on `kind`; leases an Identity | `write:collectors` |
| PATCH | `/v1/collectors/{id}` | update `config`, `instance_name`, `notes`, `desired_state` only — never `observed_state` | `write:collectors` |
| POST | `/v1/collectors/{id}/start` | sugar for `PATCH {desired_state: "running"}`; 202 Accepted, supervisor reconciles | `write:collectors` |
| POST | `/v1/collectors/{id}/stop` | sugar for `PATCH {desired_state: "stopped"}` | `write:collectors` |
| DELETE | `/v1/collectors/{id}` | hard delete; row must be in `observed_state=stopped` — server refuses live deletion | `admin:collectors` |
| GET | `/v1/collectors/{id}/memberships` | which groups this collector is currently in (filtered `left_at IS NULL`); historical with `?include_left=true` | `read:collectors` |
| GET | `/v1/stream/collectors` | SSE — `collector.*` lifecycle events for the dashboard fleet view | `stream:collectors` |
| GET | `/v1/stream/collectors/{id}` | SSE — events scoped to one collector (the detail panel) | `stream:collectors` |
| GET | `/v1/collectors/health` | fleet snapshot — count by `observed_state`, oldest stale heartbeat, restart-storm leaders | `read:collectors` |

### 3.8 Sources & SourceDomains (`/v1/sources/`)

The operator-configured platform registry. A `Source` is the configured platform/forum; `SourceDomain` rows are the hostname patterns it owns (multi-domain by design — see MODELS.md §1.1 / §2.26). Mutation here drives bridge resolution (§2.25) and candidate eligibility (§4.12.3); endpoints reflect that the storage layer enforces invariants in-transaction, not asynchronously.

| Method | Path | Purpose | Scope |
|---|---|---|---|
| GET | `/v1/sources` | list configured sources; includes count of active SourceDomains per row | `read:sources` |
| GET | `/v1/sources/{id}` | single Source with its active SourceDomain rows inlined and a summary of resolved-artifact counts | `read:sources` |
| POST | `/v1/sources` | create a Source; body MAY include an initial `domains` list (each with `pattern`, `pattern_kind`, `is_primary`, `is_onion`) — server validates the set as if added one-by-one and rejects overlap conflicts | `write:sources` |
| PATCH | `/v1/sources/{id}` | update `display_name`, `canonical_url`, `notes` — canonical_url change validates against the current primary SourceDomain per MODELS.md §1.1 | `write:sources` |
| DELETE | `/v1/sources/{id}` | refused while any `Collector.source_id` references the row OR while any `InfrastructureArtifact.resolved_to_source_id` references it — operator must reassign or accept FK SET NULL via `?force=true` (requires `admin:sources`) | `admin:sources` |
| GET | `/v1/sources/{id}/domains` | list all SourceDomain rows for this Source; `?include_removed=true` returns soft-deleted rows for audit views | `read:sources` |
| POST | `/v1/sources/{id}/domains` | add a SourceDomain; 409 with `SourceDomainOverlap` payload on conflict; `?force=true` requires `admin:sources` and marks both sides ambiguous in the bridge resolver (audited as `source_domain.overlap_forced`) | `write:sources` |
| PATCH | `/v1/sources/{id}/domains/{domain_id}` | update `is_primary` (swap primary; triggers canonical_url re-validation per MODELS.md §2.26) or `notes`; `pattern` and `pattern_kind` are immutable post-create (remove + re-add instead, preserves audit trail) | `write:sources` |
| DELETE | `/v1/sources/{id}/domains/{domain_id}` | soft-delete by default (`removed_at` populated, row retained); `?hard=true` requires `admin:sources` and fully drops the row + breaks audit chain on resolutions that referenced it | `write:sources` |
| GET | `/v1/sources/{id}/bridge-summary` | resolution counts: `{resolved, unresolved, ambiguous, irrelevant, pending_source}` aggregated across `InfrastructureArtifact` rows that target this Source | `read:sources` |

### 3.9 Discovery loop (`/v1/candidates/`, `/v1/cases/{id}/seed-roots`)

The candidate triage queue and seed-root management for the recursive-discovery loop. See §4.12 for the full lifecycle, eligibility model, and supervisor command channel. Candidate rows are populated by the discovery-driving sensor primitives defined in MODELS.md §2.27 (`channel_reference_extraction`, `url_extraction`) — operators do not write candidates by hand.

| Method | Path | Purpose | Scope |
|---|---|---|---|
| GET | `/v1/candidates` | paginated triage queue; filter by `state`, `source_id`, `case_id`, `min_score`; sorted `score DESC, last_observed_at_ingest DESC` | `read:candidates` |
| GET | `/v1/candidates/{id}` | single candidate — full mention list, score breakdown, per-collector eligibility precomputed | `read:candidates` |
| POST | `/v1/candidates/{id}/approve` | transition `queued → approved`; body picks `assigned_collector_id` (server validates eligibility) | `write:candidates` |
| POST | `/v1/candidates/{id}/reject` | transition `queued → rejected`; body requires `reason` | `write:candidates` |
| POST | `/v1/candidates/{id}/park` | transition `joined → parked` (operator-initiated leave); body requires `reason` | `write:candidates` |
| POST | `/v1/candidates/{id}/retry` | transition `failed → queued`; requires `admin:candidates` because retries on platform-rejected joins can burn identities | `admin:candidates` |
| GET | `/v1/cases/{id}/seed-roots` | list seed-root groups for a Case (`Case.seed_root_group_ids`) | `read:cases` |
| PUT | `/v1/cases/{id}/seed-roots` | replace the seed-root list — emits `case.seed_roots_changed`; recomputes candidate eligibility | `write:cases` |
| POST | `/v1/cases/{id}/seed-roots/{group_id}` | promote an existing Group to a seed root (resets depth-from-root for downstream candidates) | `admin:case` |
| GET | `/v1/stream/candidates` | SSE — `candidate.*` lifecycle events; the operator's triage feed | `stream:candidates` |

---

## 4. Auth model

### 4.1 Backing identity

`SystemUser` from `MODELS.md` §2.17 is the canonical identity. All credentials (passwords, refresh tokens, PATs) live in storage keyed by `SystemUser.id`.

New storage tables (in `eyenet/storage/`):

- `system_user_credential` — `(user_id, password_hash, password_updated_at)` — argon2id.
- `refresh_token` — `(token_id, user_id, hash, issued_at, expires_at, revoked_at, replaced_by)`.
- `personal_access_token` — `(token_id, user_id, name, hash, prefix, scopes, created_at, last_used_at, expires_at, revoked_at)`.
- `jwt_denylist` — `(jti, user_id, denied_at, expires_at)` — for forced revocation of unexpired access tokens.
- `system_user_scope` — `(user_id, scope, granted_at, granted_by_user_id)` — explicit per-user grants additive to the role baseline (§4.6). Routine read/write scopes only; clearance scopes go in the dedicated table below.
- `system_user_clearance_grant` — sensitive-tier read clearances (`read:restricted`, `read:classified`) with full grant lifecycle, mandatory expiry, and revocation history (§4.8). The court-defensibility artifact.

### 4.2 JWT shape

- **Algorithm:** RS256. Asymmetric so future verification-only services don't need the signing key.
- **Keypair:** generated on first boot to `<data_dir>/jwt/{signing_key.pem, verifying_key.pem}`, mode 0600. Rotated by appending a new keypair with a future `not_before` and serving both verifiers until old `exp` lapses.
- **`kid` format:** lowercase hex of `sha256(DER-encoded SubjectPublicKeyInfo of the verifying key)[:8]` (16 hex chars). Stable across processes, deterministic, indexable. Verifier loads all known keypairs into `{kid: verifying_key}` at boot and rebuilds on `SIGHUP`. Tokens whose `kid` is not in the map fail verification.
- **Access token claims:**
  ```json
  {
    "iss": "eyenet",
    "sub": "<system_user_uuid>",
    "iat": 1716500000,
    "exp": 1716500900,
    "jti": "<uuid7>",
    "token_type": "access",
    "kid": "<keypair fingerprint>"
  }
  ```
- **Scopes are deliberately NOT in the token.** Authority is resolved server-side per request from `system_user_scope` (see §4.4). Rationale:
  - JWT library defects (`alg:none`, alg-confusion) and key-loading misconfiguration are realistic failure modes; if a tampered token slips past verification, an attacker bounded to *the scopes a real user has* is recoverable. An attacker who can inject arbitrary `scope` claims is not.
  - Scope revocation must be effectively immediate. With scopes in the token, revocation latency = access TTL (15 min). For a scope literally named `write:panic`, 15 min is the gap between "operator fired" and "operator can still trigger global panic." Unacceptable.
  - The audit row referencing the live `system_user_scope` row at action time is reconstructable. A frozen scope claim in a long-lived token is not.
- **`token_type`** prevents cross-use: a `"stream"` token issued by `/v1/auth/stream-token` will not authorize writes; an `"access"` token will not open SSE without a fresh stream-token exchange.
- **Access TTL:** 15 minutes.
- **Refresh token:** opaque random string (32 bytes, base64url). Hashed in storage; never re-displayed. 30-day TTL. Rotates on every `/refresh` (old row marked `replaced_by`).
- **Logout:** delete refresh row; insert `jti` into `jwt_denylist` until original `exp`.

### 4.3 PATs

- Format: `eyenet_pat_<22-char-prefix>_<32-char-secret>`. Prefix is stored plaintext for display; secret is argon2id-hashed.
- Treated identically to JWT after lookup — produces the same `current_user + scopes` context.
- No refresh. Revocation is immediate via `DELETE /v1/auth/tokens/{token_id}`.

### 4.4 Permissions / scopes

Scopes are flat strings. Authority resolves from `ROLE_BASELINE[user.role] ∪ system_user_scope.where(user_id)` at request time, **not from the JWT** (see §4.2 rationale, and §4.6 for the role-vs-scope separation).

```
read:actors        read:personas       read:linkages
read:observations  read:audit          read:graph         read:metrics
read:cases                                                             # §4.10 list visible cases, read case detail for collaborated cases
read:collectors                                                        # §4.11 list/inspect collectors; config redacted unless read:collectors_config
read:collectors_config                                                 # §4.11 view full `config` JSON (chat IDs, proxy URIs) — grant-only, restricted-tier
read:candidates                                                        # §4.12 list/inspect the discovery triage queue
read:sources                                                           # §4.13 list/inspect Sources and their SourceDomains
read:restricted    read:classified                                       # §4.7 sensitivity tiers — grant-only, never in baseline
write:linkage_decision  write:identity  write:panic
write:cases                                                            # §4.10 create cases, manage members/metadata on owned cases
write:collectors                                                       # §4.11 create/update/start/stop collectors
write:candidates                                                       # §4.12 approve/reject/park candidate joins
write:sources                                                          # §4.13 create/update Sources, add/remove/repurpose SourceDomains
stream:linkages    stream:personas     stream:audit    stream:control
stream:collectors                                                      # §4.11 SSE on collector lifecycle events
stream:candidates                                                      # §4.12 SSE on candidate triage events
admin:users        admin:tokens        admin:clearance                   # admin:clearance is required to grant/revoke §4.8 clearances
admin:reclassify                                                       # §4.9 sensitivity-tier promotion — grant-only, never in baseline
admin:case                                                             # §4.10 archive/reopen, force-collaborator, archived-case access — grant-only
admin:collectors                                                       # §4.11 delete collectors, force-release leased Identity, override cooling
admin:candidates                                                       # §4.12 retry failed candidates, force-bypass dual-cover, depth-override
admin:sources                                                          # §4.13 force-overlap SourceDomain adds, force-delete Sources, hard-delete SourceDomain rows
```

Permission check is a FastAPI dependency factory: `RequireScope("write:linkage_decision")`. Returns 403 with problem+json if missing.

#### 4.4.1 Scope cache

A per-process LRU cache (`{user_id → (set_of_scopes, fetched_at)}`, TTL 60s, capacity 1024) keeps the per-request cost of scope lookup ~zero for hot users. Cache invalidation:

- **Active push**: a bus subscription on `eyenet.auth.scopes_changed` (subject emitted by `eyenet user scopes` CLI and any future admin endpoint) evicts the affected `user_id` immediately across all API processes.
- **Local triggers**: `/v1/auth/logout` evicts `user_id`; password reset evicts; `DELETE /v1/auth/tokens/{id}` evicts the owning `user_id`.
- **TTL fallback**: 60s ceiling on staleness even if a bus message is missed.

**Cache carve-out rule — uniform, not per-scope:**

The cache exists ONLY for low-stakes scopes. Every request resolves the following families from storage, every time, no cache lookup:

- `write:*` — any mutating action.
- `admin:*` — any privilege-changing action.
- `read:restricted` and `read:classified` — sensitive-evidence clearances (§4.7, §4.8). Stale clearance is unacceptable; revocation must be immediate.
- `case_member` / `case_collaborator` resolution — §4.10 membership reads bypass the cache for the same reason: a removed collaborator must lose access to the case's `classified` material within one request, not within 60 seconds. Cached scopes are not enough; the membership predicate itself is uncached.

The cache applies only to remaining `read:*` (non-sensitive) and `stream:*` scopes, which are the high-frequency hot path.

Rationale: any stale grant of a mutating, privilege-changing, or sensitive-read scope is a 60-second window in which a revoked operator can still take a real action — confirm linkages, claim identities, trigger panic, mint tokens, dereference a victim's passport. The cost-of-stale is per-scope intuitively variable but operationally identical (a fired operator with any of the above for 60s is the same incident class). One rule, no exceptions, no judgment calls in the implementation.

`RequireScope` enforces this by membership in an explicit `BYPASS_SCOPES` frozenset combined with `write:*` / `admin:*` prefix match. Adding a new bypass scope is a one-line append; adding a new `write:*` or `admin:*` scope automatically inherits the carve-out.

### 4.5 Why not `*` and why JWT at all

JWT chosen because:
- Operator UI is a browser client; cookies-with-CSRF or `Authorization: Bearer` are the realistic options. Bearer is simpler and codegen-friendly.
- RS256 lets us add read-only audit-verifier processes that can validate identity tokens without holding the signing key.
- Cryptographic identity binding: the `sub` claim is the audit-row attributable subject; that has to be tamper-evident. Authority (scopes) is a separate concern and lives in storage (§4.2, §4.4).

Note: this is **identity-in-JWT, authority-in-storage** — not "stateless auth." We pay one indexed storage read per request to resolve scopes, mitigated by the 60s cache (§4.4.1). The cost is honest and bounded.

mTLS rejected for v1: ops cost (cert distribution, rotation) outpaces value at this scale. Reconsider when there are >5 integrators.

### 4.6 Role vs. scope — the explicit separation

**Role** is the coarse RBAC tier (one per user, displayed on the dashboard). **Scope** is the fine-grained authorization gate enforced at every endpoint. They are **orthogonal axes**; the system never collapses one into the other.

- `SystemUser.role: SystemUserRole` — one of `admin`, `analyst`, `viewer`. Shapes the UI defaults and the baseline scope set. Role changes are rare and require `admin:users`.
- `system_user_scope.granted: list[scope]` — explicit per-user grants the admin manages, **additive** on top of the role baseline. Grants are revocable individually without touching the user's role.

**`ROLE_BASELINE` is a frozen mapping in code, not configuration**, so the entire baseline policy is reviewable in one diff and cannot drift via runtime config changes:

```python
# eyenet/api/auth/permissions.py
from typing import Mapping
from eyenet.contracts.enums import SystemUserRole

ROLE_BASELINE: Mapping[SystemUserRole, frozenset[str]] = {
    SystemUserRole.ADMIN: frozenset({
        "read:actors", "read:personas", "read:linkages", "read:observations",
        "read:audit", "read:graph", "read:metrics", "read:cases",
        "write:linkage_decision", "write:identity", "write:cases",
        "stream:linkages", "stream:personas", "stream:audit", "stream:control",
        "admin:users", "admin:tokens",
    }),
    SystemUserRole.ANALYST: frozenset({
        "read:actors", "read:personas", "read:linkages", "read:observations",
        "read:audit", "read:graph", "read:cases",
        "write:linkage_decision", "write:identity", "write:cases",
        "stream:linkages", "stream:personas",
    }),
    SystemUserRole.VIEWER: frozenset({
        "read:actors", "read:personas", "read:linkages", "read:graph",
    }),
}

# NEVER in any baseline — grant-only, audited, time-bound:
#   read:restricted    (§4.7, §4.8)
#   read:classified    (§4.7, §4.8)
#   write:panic        (kill-switch — requires explicit grant even for admins)
#   admin:clearance    (authority to grant/revoke clearance scopes)
#   admin:reclassify   (§4.9 — authority to promote sensitivity tier on evidence)
#   admin:case         (§4.10 — archive/reopen, force-collaborator, archived-case access)
```

**Effective scope set** at every authorization check:

```
effective(user) = ROLE_BASELINE[user.role] ∪ active_grants(user.id)
```

where `active_grants(user.id)` UNIONS rows from `system_user_scope` and active rows from `system_user_clearance_grant` (see §4.8).

`UserMe.scopes` returned by `/v1/auth/me` is the **effective** set — what the caller can actually do, not their role's baseline. This is the single source of truth the UI uses to decide which buttons to render.

`RequireScope("write:linkage_decision")` checks the effective set. **Role is never consulted at the endpoint** — it is a UI label and a baseline-seed, nothing more. An admin without the right grant is denied like anyone else; that is an intentional design property, not an accident.

### 4.7 Evidence sensitivity tiers

EYENET targets APT-tier evidence collection. The corpus will, with high probability, contain personally identifying information, government IDs, health records, and material that could re-identify real victims. The default read posture must be **least access**, not "if you can list it, you can read it."

`Observation`, `Message`, and `Attachment` (file blob) rows each carry **two** sensitivity columns:

| Column | Mutability | Set by | Meaning |
|---|---|---|---|
| `classifier_tier: SensitivityTier` | Immutable. Set once at ingest, never updated. | The classifier (§4.9.1) — a deterministic detector chain that runs on every ingested row before it lands. | The machine's read. The lower bound on the row's effective tier, for all time. |
| `operator_tier_override: SensitivityTier \| NULL` | Monotone ↑ only. Storage-layer CHECK rejects any UPDATE that lowers the value. NULL means "no override". | Operator action via `POST /v1/{observations,attachments}/{id}/reclassify` (§4.9). Requires `admin:reclassify`. | An operator's promotion above what the classifier picked. Cannot demote the classifier's tier; can only raise it. |

The **effective tier** read at every dereference is:

```
effective_tier(row) = max(row.classifier_tier, row.operator_tier_override OR row.classifier_tier)
```

implemented as a SQL `COALESCE(operator_tier_override, classifier_tier)` because the monotonicity CHECK guarantees the override, when present, is `>=` the classifier value. Endpoints use `effective_tier` for all clearance gating. The two underlying columns are exposed only on detail endpoints to clearance holders, for forensic reconstruction.

**Why two columns instead of one:** preserves the classifier's verdict as evidence in its own right. If the operator promotes `normal → classified` based on context the classifier couldn't see, the audit trail records both values — the operator can never make the classifier "have always said" the higher tier, which closes the obvious tampering vector. See §4.9 for the reclassification flow.

Observations and attachments carry these columns **independently**. A `normal` text message ABOUT a `classified` attachment is read at `normal`; the attachment is read at `classified`. A redacted preview of a classified attachment embedded inline in a message bumps the message tier to at least `restricted`, applied by the classifier at ingest. There is no implicit inheritance — each row is independently classified, and effective tier is per-row.

| Tier | What lives here | Required read scopes |
|---|---|---|
| `normal` | Public posts, handles, observed timestamps, statistical/derived primitives | `read:observations` |
| `restricted` | PII fragments (real names, emails, phone numbers, home/work addresses), private group context, screen-name⇄legal-name correlations | `read:observations` AND `read:restricted` |
| `classified` | Passport / national-ID scans, health records, identifying photos of real victims, source materials whose disclosure could re-victimize an identifiable person | `read:observations` AND `read:classified` |

**Tier assignment:**
- The **classifier** (§4.9.1) is authoritative at ingest. Its verdict is written to `classifier_tier` and is never modified after the row is committed.
- The **operator** can promote via `POST /v1/observations/{id}/reclassify` or `POST /v1/attachments/{blob_id}/reclassify` (§4.9), holding `admin:reclassify`. Promotion is recorded in `operator_tier_override`; demotion is rejected by storage CHECK and again by the endpoint.
- `effective_tier` is `COALESCE(operator_tier_override, classifier_tier)`. There is no code path through which `effective_tier` decreases over the lifetime of a row. Re-redaction or row deletion (both audited) are the only mechanisms that change the surface, neither of which alters `classifier_tier`.
- The classifier's fallback verdict is `normal`. A classifier that fails to run (collector misconfiguration) MUST write `normal` and emit `eyenet.audit.classifier.failed` — the row is still ingested, but the audit trail makes the failure visible. Defaulting `normal` is a recorded failure mode, not a routine policy.

**Endpoint behavior — redaction, not omission:**

- **List / timeline endpoints** (`/v1/actors/{id}/observations`, `/v1/actors/{id}/timeline`): rows above the caller's clearance ARE returned, with the `content` (and any other sensitive field) replaced by a `RedactionMarker` shape:
  ```json
  { "redacted": true, "tier": "classified", "reason": "missing scope read:classified",
    "request_clearance_at": "/v1/auth/me", "grant_request_subject": "evidence_access" }
  ```
  Metadata (`id`, `ts`, `kind`, `primitive`, `score`) remains visible. Analysts can SEE that sensitive evidence exists, count it, and ESCALATE to a clearance holder — they just cannot read the body. This is deliberate: hiding the existence of evidence is corrosive to investigative workflow; gating its contents is the auditable line.
- **Detail / direct-fetch endpoints**: same redaction rule. The 200 envelope is preserved; the sensitive fields are replaced.
- **Audit endpoints** (`/v1/audit*`): audit rows are themselves tier-`normal`. The audit trail is not the evidence. A row's `payload` may reference an evidence row's id and tier, but never its content.

**OpenAPI surfacing:** `RedactionMarker` is a top-level named component schema in `eyenet.v1.yaml`; every field that can be replaced by it uses `oneOf: [<original>, {$ref: RedactionMarker}]` (or the polymorphic-content wrapper pattern). Schemathesis fuzzes both shapes.

### 4.8 Clearance grant lifecycle — the court-defensible artifact

Every grant of `read:restricted` or `read:classified` is an explicit, justified, time-bound, individually-revocable, fully-audited operator decision. There is no implicit clearance. There is no role that confers it. The audit trail must be sufficient, on its own, to answer the question "who let this person see this person's passport, and why, and when, and were they still authorized to do so at the moment of access?"

**Storage table** `system_user_clearance_grant`:

| Column | Type | Constraints / notes |
|---|---|---|
| `grant_id` | UUID7 | Primary key. Stable ID referenced from every `evidence_access.restricted` / `evidence_access.classified` audit row. |
| `user_id` | UUID | The grantee. |
| `scope` | string | One of `read:restricted`, `read:classified`. CHECK constraint. |
| `granted_by_user_id` | UUID | Granting admin. **Must hold `admin:clearance` at grant time** — enforced at the endpoint, asserted again at storage layer. |
| `reason` | text, length ≥ 16, ≤ 1024 | **Mandatory** justification. Free text, but minimum length enforced — "ok" is not a reason. Expected content: case identifier, incident ID, operator rationale, peer-review reference. |
| `granted_at` | datetime, UTC | Set by the storage layer, not the caller. |
| `expires_at` | datetime, UTC | **Mandatory.** CHECK: `expires_at <= granted_at + INTERVAL '90 days'`. Re-granting is one row insert, not an UPDATE. |
| `revoked_at` | datetime, UTC, nullable | Set on explicit revocation. |
| `revoked_by_user_id` | UUID, nullable | The revoking admin. Required if `revoked_at IS NOT NULL`. |
| `revocation_reason` | text, length ≥ 1, ≤ 1024, nullable | Mandatory iff `revoked_at IS NOT NULL`. |
| `parent_grant_id` | UUID, nullable | If this row is a renewal, the prior `grant_id` it succeeds. Lets the chain be reconstructed. |

**Active-grant predicate** (the only test the scope resolver runs):
```
ACTIVE(now) :=
    granted_at <= now
    AND expires_at > now
    AND revoked_at IS NULL
```
Expiry is enforced **at the resolver**, not by a cron. A row that has expired but is still present is harmless (and forensically useful — it records that the clearance existed once). No background job ever needs to run for safety.

**Mandatory audit events** (subjects under `eyenet.audit.*`, each a row in the audit log via the §5 contract):

| Subject | Trigger | Payload anchors |
|---|---|---|
| `eyenet.audit.clearance.granted` | Insert into `system_user_clearance_grant` | `grant_id`, `user_id`, `scope`, `granted_by_user_id`, `reason`, `granted_at`, `expires_at` |
| `eyenet.audit.clearance.revoked` | Set `revoked_at` | `grant_id`, `revoked_by_user_id`, `revocation_reason`, `revoked_at` |
| `eyenet.audit.clearance.expired` | First observation by the resolver that `expires_at <= now()` for a row with `revoked_at IS NULL`. Idempotent — guarded by a "first observation" marker so exactly one row exists per grant lifecycle. | `grant_id`, `expired_at` (= `expires_at`) |
| `eyenet.audit.evidence_access.restricted` | Any dereference (read/list with body) of a `restricted` row by a non-admin scope holder | `subject_kind=evidence`, `subject_id`, `grant_id` that authorized the access |
| `eyenet.audit.evidence_access.classified` | Same, for `classified` | same shape |

The `grant_id` linkage is **non-negotiable**: an `evidence_access.restricted` row with no `grant_id` is a contract violation and the endpoint must fail closed with 503 rather than serve.

**Cache rule:** `read:restricted` and `read:classified` are in the cache-bypass set (§4.4.1). Resolved from storage on every request. Revocation is immediate.

**`admin:clearance` is itself a grant-only scope.** It does NOT appear in any role baseline. The bootstrap admin's first `admin:clearance` is seeded by `eyenet user grant-bootstrap-clearance` (a CLI command, audited with `granted_by_user_id = SYSTEM_BOOTSTRAP_UUID` — a sentinel value that never matches a real user). Every subsequent grant of `admin:clearance` is itself an admin-to-admin transaction with its own audit row. There is no chicken-and-egg path that lets a non-admin self-elevate.

**Court-defensible reconstruction** — given a single `evidence_access.classified` audit row from production:
1. Read `grant_id` from the payload.
2. JOIN `system_user_clearance_grant` ON `grant_id` → returns the granting admin's UUID, the justification text, the granted/expires/revoked timestamps.
3. The grant row's `granted_by_user_id` resolves to a real `SystemUser` with a `system_user_credential` row.
4. The granting admin's own `admin:clearance` is itself a `clearance.granted` audit row, traceable back through `parent_grant_id` to either another admin or `SYSTEM_BOOTSTRAP_UUID`.
5. The chain terminates at bootstrap. There is always a person, a reason, a clock, and an unbroken chain of authority.

There is no "the system gave it to them." There is no "default permission." Every access to a victim's sensitive data is one explicit human decision, time-bounded, justified in writing, and individually revocable.

### 4.9 Reclassification — promoting evidence sensitivity after ingest

The classifier (§4.9.1) commits a tier at ingest. Reality is more complicated than any detector chain: a handle that looked anonymous gets identified, a filename that meant nothing reveals a target, a file's metadata is reread under a different threat model. The operator must be able to **promote** a row's effective tier without ever being able to **lower** what the machine already said.

**Scope.** `admin:reclassify` is a grant-only scope. It is not in any role baseline (§4.6). It is granted through the same §4.8 lifecycle as `read:restricted` / `read:classified`: ≤90-day expiry, mandatory reason, individually revocable, audit chain terminating at `SYSTEM_BOOTSTRAP_UUID`.

**Monotonicity is enforced at THREE layers:**

1. **Endpoint guard** — rejects `new_tier <= effective_tier(row)` with 422 problem+json.
2. **Storage CHECK constraint** on `attachment` / `observation` UPDATE:
   ```sql
   CHECK (NEW.operator_tier_override IS NULL
          OR NEW.operator_tier_override >= NEW.classifier_tier)
   CHECK (OLD.operator_tier_override IS NULL
          OR NEW.operator_tier_override >= OLD.operator_tier_override)
   ```
3. **Audit row** — every reclassification records both `prior_effective_tier` and `new_tier`; downstream audit consumers detect any contract violation post-hoc.

A defect in any one layer is caught by the other two. The legal posture of EYENET requires that "the operator downgraded classified evidence" is **structurally unreachable**, not merely discouraged.

**Mandatory inputs on the request body:**

| Field | Constraint |
|---|---|
| `new_tier` | `restricted` or `classified`. Cannot reclassify to `normal`. |
| `reason` | Text, **length ≥ 32**, ≤ 1024. Expected content: case identifier, triggering observation, peer-review reference. |
| `viewing_context` | Optional free text — what the operator was doing when they made the call (e.g. `"reviewing case=APT-29 evidence batch 3"`). Stored verbatim in the audit row. |
| `operator_signature` | Ed25519 signature over the canonical request form (§5.7). Without it the endpoint fails closed with 403 — the system never reclassifies on the strength of a session cookie or JWT alone. |

**Audit events** (written through §5.1 / §5.2 contracts, both bus and storage):

| Subject | Trigger | Payload anchors |
|---|---|---|
| `eyenet.audit.reclassify.observation` | `POST /v1/observations/{id}/reclassify` succeeds | `observation_id`, `user_id`, `grant_id`, `prior_effective_tier`, `new_tier`, `classifier_tier`, `reason`, `viewing_context`, `operator_signature_pubkey_fingerprint` |
| `eyenet.audit.reclassify.attachment` | `POST /v1/attachments/{blob_id}/reclassify` succeeds | `blob_id`, `content_hash`, `user_id`, `grant_id`, `prior_effective_tier`, `new_tier`, `classifier_tier`, `reason`, `viewing_context`, `operator_signature_pubkey_fingerprint` |
| `eyenet.audit.reclassify.rejected` | Endpoint guard rejects (would-be demotion, missing scope, bad signature, expired grant) | `subject_id`, `subject_kind`, `attempted_tier`, `current_effective_tier`, `rejection_reason`, `user_id` |
| `eyenet.audit.classifier.failed` | Classifier crashed or skipped a row at ingest; row stored with `classifier_tier=normal` as fallback | `subject_id`, `subject_kind`, `classifier_id`, `error_class` |

The `reclassify.rejected` event is non-negotiable: a refused reclassification attempt is itself evidence of intent and must be permanent and queryable. Operators who repeatedly probe for downgrade paths are flagged by routine audit review.

**Replay invariant:** given the audit log alone, the effective tier of every row at every point in time is reconstructable. Storage is a cache of the audit chain on this axis, not the source of truth. This is the same invariant §5 maintains for access events; reclassification extends it.

#### 4.9.1 The classifier — design surface, not implementation

The classifier is a separate concern from the API layer; this section pins its **contract**, not its internals. The implementation is the next conversation after this spec.

- **Where it runs:** in the collector tier, between the raw-event sink and the row's first storage commit. The classifier sees the canonical row form (text, metadata, attachment manifest) BEFORE the row is visible to any read path.
- **Determinism:** the classifier is a pure function of `(row, ruleset_version)`. The same row classified twice under the same ruleset produces the same verdict. Non-determinism (LLM heuristics, network calls) is forbidden in the production path; experimental classifiers run offline and surface as *suggestions* an operator accepts via `admin:reclassify`.
- **Ruleset versioning:** every classifier invocation records its `ruleset_version` (semver) alongside the tier verdict on the row. An audit consumer can ask "would this row classify differently under the current rules?" without re-running the classifier. A rule change does NOT retroactively re-tier history — corpus re-classification under a new ruleset is per-row `admin:reclassify` work, with the prior tier preserved.
- **Failure mode:** classifier exceptions MUST write `classifier_tier=normal` AND emit `eyenet.audit.classifier.failed`. The pipeline never fail-closes on classifier errors — that would be a DoS vector against ingestion — but the audit makes the failure unmissable.
- **No `classifier_tier` UPDATE path:** the classifier never modifies an existing row. Every visible change is therefore an explicit operator decision via `admin:reclassify`, with the machine's original verdict preserved as evidence in its own right.

**Detector chain shape** (illustrative, NOT a frozen surface):

```python
# eyenet/classifier/chain.py — sketch
class Detector(Protocol):
    name: str
    def detect(self, row: ClassifiableRow) -> SensitivityTier | None: ...

def classify(row: ClassifiableRow, chain: list[Detector]) -> ClassifierVerdict:
    fired = [(d.name, t) for d in chain if (t := d.detect(row)) is not None]
    tier = max((t for _, t in fired), default=SensitivityTier.NORMAL)
    return ClassifierVerdict(
        tier=tier,
        contributing_detectors=[name for name, _ in fired],
        ruleset_version=...,
    )
```

Concrete detectors expected in the first cut (each warrants its own design conversation):

- `RegexIdDetector` — passport / national-ID / SSN / IBAN-shaped tokens → `classified`.
- `MimeImageIdDetector` — image attachments matching ID-card layout heuristics (v0: presence-of-faces + MRZ-text patterns; later: trained model) → `classified`.
- `PiiPatternDetector` — email / phone / address regexes → `restricted`.
- `NatoMarkingDetector` — text containing `NATO`, `NOFORN`, `RESTRICTED`, `CONFIDENTIAL` markings in formatted-document context → `classified`. Defends the scenario in [[project_file_access_journal]] where filenames reveal pedigree.
- `DmContextDetector` — row collected from a private conversation rather than a public channel → `restricted` floor.
- `FilenamePedigreeDetector` — attachment filename matches known classified-document naming conventions → `classified`.

The classifier ships with a default chain and a per-deployment override file. Override files are themselves audited on load (`eyenet.audit.classifier.ruleset_loaded`). No silent ruleset changes.

### 4.10 Cases — the investigation primitive

§4.7 / §4.8 / §4.9 all talk about `case=APT-29` in `reason` fields as if cases were real objects. They are not. Without a Case API, "case=APT-29" is a free-text convention with **zero referential integrity, zero lifecycle, zero authority chain** — a prosecutor asking "what was case APT-29?" gets a `grep` result, which is not evidence. This section makes cases first-class.

A **case** is an operator-defined collection of evidence (observations, attachments, messages, actors, personas, linkages) that share an investigative purpose. Cases own:

- A UUID and a stable referenceable identity.
- A lifecycle: `open → closed → archived` (one-way except via `admin:case` reopen).
- A membership graph: many-to-many across all subject kinds, soft-deleted (rows mark `removed_at`, never disappear).
- A collaborator roster: who is authorised to see the case as a unit.
- An effective tier: `max` of the effective tier of all currently-active members.
- An audit chain: every state-changing action emits an `eyenet.audit.case.*` subject (§5.1 / §5.2).

#### 4.10.1 Storage

**Table `case`** (lives in the audit-domain DB alongside §4.8 grants):

| Column | Type | Constraints / notes |
|---|---|---|
| `case_id` | UUID7 | PK. Referenced from `case_member`, `case_collaborator`, and every `case_ref` array in `grant.reason` / `reclassification.reason` / `file_access.viewing_context`. |
| `title` | text, 4–256 | Operator-supplied. Stable case label (e.g. `APT-29 recruitment activity 2026Q2`). |
| `description` | text, ≤8192, nullable | Free text. Updatable while `status == open`. |
| `status` | string | One of `open`, `closed`, `archived`. CHECK constraint. |
| `created_by_user_id` | UUID | Foreign-keyed to `system_user`. Required `write:cases`. |
| `created_at` | datetime, UTC | Set by storage layer. |
| `closed_at` | datetime, UTC, nullable | Set on transition to `closed`. |
| `closed_by_user_id` | UUID, nullable | Required when `closed_at IS NOT NULL`. |
| `close_reason` | text, 16–1024, nullable | Required when `closed_at IS NOT NULL`. |
| `archived_at` | datetime, UTC, nullable | Set on transition to `archived`. |
| `archived_by_user_id` | UUID, nullable | Required when `archived_at IS NOT NULL`. Holder must have `admin:case`. |
| `archive_reason` | text, 16–1024, nullable | Required when `archived_at IS NOT NULL`. |
| `parent_case_id` | UUID, nullable | If this case succeeds another (rename, scope-split, post-reopen renumber), the prior `case_id`. Lets the chain reconstruct. |
| `effective_tier` | string | `normal` / `restricted` / `classified`. Materialised column updated on every member add/remove. Cheap reads for case listing. The §4.7 `effective_tier(row)` rule is independently re-verifiable from `case_member`. |

**Table `case_member`** (m:n junction, soft-delete by `removed_at`):

| Column | Type | Constraints / notes |
|---|---|---|
| `member_id` | UUID7 | PK. Stable handle a `DELETE /members/{member_id}` references. |
| `case_id` | UUID | FK → `case`. |
| `subject_kind` | string | `observation` / `attachment` / `message` / `actor` / `persona` / `linkage`. CHECK. |
| `subject_id` | UUID | The member's id in its own table. Referential integrity is enforced at the storage *layer*, not by SQL FK (members span 8 DBs — see [[project_storage_eight_databases]]). |
| `added_by_user_id` | UUID | Required `write:cases`. |
| `added_at` | datetime, UTC | Set by storage layer. |
| `add_reason` | text, 16–1024 | Mandatory. Justification for inclusion. |
| `removed_at` | datetime, UTC, nullable | Soft-delete marker. |
| `removed_by_user_id` | UUID, nullable | Required when `removed_at IS NOT NULL`. |
| `removal_reason` | text, 16–1024, nullable | Required when `removed_at IS NOT NULL`. |

Uniqueness: `(case_id, subject_kind, subject_id) WHERE removed_at IS NULL` — a subject is a member of a given case at most once *currently*; its full add/remove history is preserved in soft-deleted rows.

**Table `case_collaborator`** (ACL — who can act on the case):

| Column | Type | Constraints / notes |
|---|---|---|
| `collaborator_id` | UUID7 | PK. |
| `case_id` | UUID | FK → `case`. |
| `user_id` | UUID | The collaborator. |
| `role_on_case` | string | `owner` / `analyst` / `reviewer`. CHECK. The case creator is automatically `owner`. |
| `granted_by_user_id` | UUID | Owner of the case OR holder of `admin:case`. |
| `granted_at` | datetime, UTC | |
| `revoked_at` | datetime, UTC, nullable | Soft-revoke. |
| `revoked_by_user_id` | UUID, nullable | Required when `revoked_at IS NOT NULL`. |
| `revocation_reason` | text, 1–1024, nullable | Required when `revoked_at IS NOT NULL`. |

#### 4.10.2 Scopes

Three new scopes join the §4.4 catalogue:

| Scope | Baseline | Purpose |
|---|---|---|
| `read:cases` | analyst, admin | List cases visible to the caller (subject to the §4.10.4 visibility predicate); read case detail and member lists for cases the caller collaborates on. |
| `write:cases` | analyst, admin | Create cases, edit own metadata, add/remove members on cases the caller owns or co-analyses. |
| `admin:case` | **grant-only** (joins ClearanceScope, §4.8) | Archive / reopen cases, force-add collaborators, override ownership decisions, access archived cases. Same ≤90-day grant lifecycle as other clearance scopes. |

`admin:case` is the second non-read clearance scope (after `admin:reclassify`). Same lifecycle, same audit chain. Never in any baseline.

#### 4.10.3 Lifecycle

```
                       admin:case
                  ┌──────────────────┐
                  │                  ▼
   open ────close──────► closed ──archive──► archived
   ▲                       │                    │
   └───────reopen──────────┘                    │
                  (write:cases on case owner)   │
                  ▲                             │
                  └─────reopen (admin:case)─────┘
```

State transitions:

| From → to | Required scope | Required body |
|---|---|---|
| `open → closed` | `write:cases` AND caller is `owner` of the case (or holds `admin:case`) | `close_reason` ≥ 16 chars |
| `closed → open` | `write:cases` AND caller is `owner` (or holds `admin:case`) | `reopen_reason` ≥ 16 chars |
| `closed → archived` | `admin:case` | `archive_reason` ≥ 32 chars |
| `archived → open` | `admin:case` | `reopen_reason` ≥ 32 chars (creates a new case row with `parent_case_id` pointing at the archived one — the archived row stays archived forever) |

Properties:

- `closed` cases reject ALL `POST/PATCH/DELETE` on members and metadata. Member add/remove returns 409. Title/description edits return 409. Readable normally subject to §4.10.4.
- `archived` cases are invisible to standard list/detail endpoints — they require `admin:case` even to enumerate. The audit log still references them by id forever.
- Reopening from `archived` does NOT mutate the archived row. It creates a successor case linked via `parent_case_id`. The legal trail of "this evidence was once locked into an archived case" is preserved.

#### 4.10.4 Hybrid access model — classified rows require case membership

The headline rule that makes Case API load-bearing:

```
can_read_row(user, row):
    tier = effective_tier(row)
    if tier == NORMAL:
        return has_scope(user, "read:observations")  # or appropriate row-kind scope
    if tier == RESTRICTED:
        return has_scope(user, "read:observations") AND has_scope(user, "read:restricted")
    if tier == CLASSIFIED:
        return (
            has_scope(user, "read:observations")
            AND has_scope(user, "read:classified")
            AND exists_case_membership(user, row)  # ← the new ring
        )
```

where:

```
exists_case_membership(user, row):
    return EXISTS(
        SELECT 1
          FROM case_member cm
          JOIN case_collaborator cc USING (case_id)
          JOIN case c USING (case_id)
         WHERE cm.subject_kind = row.kind
           AND cm.subject_id   = row.id
           AND cm.removed_at IS NULL
           AND cc.user_id   = :user_id
           AND cc.revoked_at IS NULL
           AND c.status IN ('open', 'closed')  -- archived cases don't confer access
    )
```

`normal` and `restricted` are still per-row-tier — the operational reality of analyst work would grind to a halt if every routine PII fragment required case attribution. `classified` material is the heavy-hitter category that DOES require explicit case attribution; an analyst with broad `read:classified` cannot wander the corpus of passports.

**Listing implications:**

A case is visible in `GET /v1/cases` to a caller if:
```
effective_tier(case) <= max_tier_scope(user)
AND (effective_tier(case) != CLASSIFIED OR user collaborates on the case)
```

The second clause prevents enumeration of classified-case *titles* by anyone with `read:classified` but no membership. The existence of the case is itself sensitive metadata.

**Cache rule:** `case_member` and `case_collaborator` resolution is in the §4.4.1 cache-bypass set. Membership/collaborator changes propagate immediately. Same operational rationale as clearance grants — a removed collaborator must lose access within one request, not within 60 seconds.

#### 4.10.5 Case effective tier

A case's `effective_tier` is materialised on the `case` row and updated synchronously on every member add/remove:

- `add_member`: `case.effective_tier = max(case.effective_tier, effective_tier(row))`.
- `remove_member`: if the removed member's tier == case tier, **recompute** from remaining active members. Otherwise no-op.
- `reclassification` of a member (§4.9): the reclassify endpoint propagates the new tier into every case that has an active membership for the row. Each case promotion emits `eyenet.audit.case.tier_changed` and atomically updates `effective_tier`.

A case's tier is **monotone-up within an open lifecycle** — closing/reopening can reset it via member set changes, but no individual operator action can lower it. Same legal posture as §4.9 for rows.

#### 4.10.6 Audit subjects

| Subject | Trigger | Payload anchors |
|---|---|---|
| `eyenet.audit.case.created` | `POST /v1/cases` | `case_id`, `title`, `created_by_user_id`, `created_at` |
| `eyenet.audit.case.updated` | `PATCH /v1/cases/{id}` (title or description) | `case_id`, `prior_title`, `new_title`, `prior_description_sha256`, `new_description_sha256`, `user_id`, `reason` |
| `eyenet.audit.case.member_added` | `POST /v1/cases/{id}/members` | `case_id`, `member_id`, `subject_kind`, `subject_id`, `added_by_user_id`, `add_reason`, `member_effective_tier_at_add` |
| `eyenet.audit.case.member_removed` | `DELETE /v1/cases/{id}/members/{member_id}` | `case_id`, `member_id`, `removed_by_user_id`, `removal_reason` |
| `eyenet.audit.case.collaborator_added` | `POST /v1/cases/{id}/collaborators` | `case_id`, `collaborator_id`, `user_id`, `role_on_case`, `granted_by_user_id` |
| `eyenet.audit.case.collaborator_revoked` | `DELETE /v1/cases/{id}/collaborators/{collaborator_id}` | `case_id`, `collaborator_id`, `revoked_by_user_id`, `revocation_reason` |
| `eyenet.audit.case.closed` | `POST /v1/cases/{id}/close` | `case_id`, `closed_by_user_id`, `close_reason` |
| `eyenet.audit.case.reopened` | `POST /v1/cases/{id}/reopen` (from closed) OR new case via archived-reopen | `case_id`, `prior_status`, `parent_case_id`, `reopened_by_user_id`, `reopen_reason` |
| `eyenet.audit.case.archived` | `POST /v1/cases/{id}/archive` | `case_id`, `archived_by_user_id`, `archive_reason` |
| `eyenet.audit.case.tier_changed` | Effective tier transition on add / remove / member reclassification | `case_id`, `prior_tier`, `new_tier`, `triggering_member_id`, `triggering_event_id` |
| `eyenet.audit.case.access_denied` | A read request was refused because the caller lacked case membership for a `classified` row | `case_id` (if known), `subject_kind`, `subject_id`, `user_id`, `effective_tier` |

The `access_denied` event is the case-API analogue of §4.9's `reclassify.rejected` — refused access attempts are themselves evidence and must be permanent.

#### 4.10.7 Cross-references — `case_refs` everywhere a `reason` was free text

The structural fix to "case=APT-29 was just a string" — every `reason`-bearing surface in §4.7 / §4.8 / §4.9 / §5.6 gains a sibling `case_refs: list[UUID]` field:

| Endpoint | Field | Semantics |
|---|---|---|
| `POST /v1/clearance/grants` (§4.8) | `case_refs` | Cases this grant is being issued for. Server validates each case exists and is `open`. Optional but recommended. |
| `POST /v1/observations/{id}/reclassify` (§4.9) | `case_refs` | Cases where this row is evidence. Server validates each exists. Optional. |
| `POST /v1/attachments/{blob_id}/reclassify` (§4.9) | `case_refs` | Same. Optional. |
| `POST /v1/attachments/{blob_id}/access` (§5.6, `FileAccessAcknowledgment`) | `case_refs` | Cases the operator is working under for this access. The journal row preserves them. Optional, but cleared access to a `classified` row REQUIRES at least one `case_ref` resolving to a case where the row is a member and the operator is a collaborator — this is how §4.10.4's hybrid rule manifests at the byte-fetch layer. |
| `POST /v1/cases/{id}/members` | `add_reason` (already required); plus implicit `case_id` from the path | Adding a member is itself a case_ref by construction. |

Audit subjects' payloads gain `case_refs` everywhere a reason is recorded. Court-defensible reconstruction:

> "Who accessed passport-blob-X on 2026-05-24 12:14:33?" → file_access_journal row → audit_event → `case_refs: [APT-29]` → case_collaborator on APT-29 at that time → SystemUser → granted_by chain → bootstrap.

The chain is now structural, not textual.

---

### 4.10a Persona action model — operator merge / split

Added 2026-09-21 for M9.G4. A `Persona` (MODELS.md) is the union-find grouping of
actors the system believes are one human. Normally personas form **automatically**:
when an operator confirms a linkage, the Graph service calls
`merge_actors_into_persona(actor_a, actor_b, via_linkage_id=...)`. §4.10a defines
the two **manual overrides** an operator needs when the automatic path is wrong.

**Why manual overrides exist.** The classifier/linker propose; the operator
adjudicates. Two failure modes need a human: the graph *failed to link* two
actors that are obviously one person (merge), or it *over-linked* — folded a
distinct human into a persona (split). Both are operator-grade forensic
decisions and are audited as `operator_action`.

| Method | Path | Body | Bus subject | Applier |
|---|---|---|---|---|
| POST | `/v1/personas/{persona_id}/merge` | `PersonaMergeRequest` | `attribution.persona.merge` | Graph |
| POST | `/v1/personas/{persona_id}/split` | `PersonaSplitRequest` | `attribution.persona.split` | Graph |

```python
class PersonaMergeRequest(ApiSchema):
    other_persona_id: UUID          # the persona to fold INTO {persona_id}
    reason: str                     # mandatory operator justification (audited)
    case_refs: list[str] = []       # §4.10.7 cross-references

class PersonaSplitRequest(ApiSchema):
    actor_id: UUID                  # the member actor to pull OUT of {persona_id}
    reason: str
    case_refs: list[str] = []
```

**Semantics.**
- *Merge* folds `other_persona_id` into `{persona_id}`. Because the storage
  primitive operates on actors (`merge_actors_into_persona(a, b, via_linkage_id)`),
  the applier resolves a representative member actor from each persona and merges
  with `via_linkage_id=None` (an operator merge has no backing linkage — the
  `reason` + audit row carry the justification). `422` if `other_persona_id ==
  persona_id` or is not a distinct persona.
- *Split* pulls `actor_id` out of `{persona_id}` via
  `split_actor_from_persona(actor_id)`. `422` if `actor_id` is not a current
  member.

**Lifecycle (async, mirrors §10.3).** The API persists the audit + a
`persona_event_log` row and publishes the command; it does **not** mutate the
persona graph directly (invariant #2). Graph consumes the command, applies the
merge/split, and emits the existing `attribution.persona.updated` so the read
side and any SSE subscribers converge. The `202` body is
`WriteAccepted{applied:false, poll:"/v1/personas/{persona_id}"}`.

**Scope.** `write:persona_decision` — admin + analyst baseline, mirroring
`write:linkage_decision`. It is a decision scope, not `admin:*`.

---

### 4.11 Collectors — the runtime fleet

`Collector` (MODELS.md §2.19) is a first-class API resource because the UI is the operator's only entry point for spinning up, configuring, and supervising the things that pull bytes off platforms. A `Collector` is the binding of:

- a `Source` (which platform — telegram/matrix/...),
- an `Identity` (which credential — exclusive lease),
- a `kind`-specific `config` blob (which chats/rooms, rate caps, proxy overrides),
- an operator-expressed `desired_state` (running / stopped / disabled),
- and a supervisor-reported `observed_state` (stopped / starting / running / cooling / crashed).

#### 4.11.1 Process model — in-process async supervisor

A single `CollectorSupervisor` service runs inside the EYENET process group (next to the bus, the storage, the API). It owns the live fleet:

```python
# eyenet/services/collector_supervisor.py — sketch
class CollectorSupervisor(ServiceBase):
    name = "collector_supervisor"
    _tasks: dict[UUID, asyncio.Task[None]]   # collector_id → live task
    _leases: dict[UUID, UUID]                # collector_id → identity_id

    async def tick(self) -> None:
        # Reconcile desired_state → observed_state for every row.
        # Start tasks for rows that want running but aren't.
        # Stop tasks for rows that want stopped but are running.
        # Mark observed_state=crashed and emit collector.crashed on task exception.
        # Apply exponential backoff (restart_count) before re-starting crashed rows.
```

**One supervisor per EYENET instance. Not configurable.** Multi-host fleets are out of scope for v0 — small-operator scope (CLAUDE.md §1). When that changes, a per-supervisor `host_id` column gates the reconcile predicate; the API contract here does not change.

Default backend is `asyncio.Task` (Telethon and `nio` are both fully async — no fork needed). A future `subprocess.Popen` backend behind the same `CollectorBackend` interface is reserved for collectors that need OS isolation (a C extension that segfaults, an embedded browser for forum scraping). The API contract above is backend-agnostic.

#### 4.11.2 Lifecycle

```
       ┌──────────┐  start  ┌──────────┐  ready  ┌─────────┐
       │ stopped  │────────▶│ starting │────────▶│ running │
       └──────────┘         └──────────┘         └─────────┘
            ▲                    │                    │
            │ stop               │ start fail         │ crash
            │                    ▼                    ▼
            │              ┌──────────┐  cooldown  ┌─────────┐
            └──────────────│ crashed  │◀───────────│ cooling │
                           └──────────┘            └─────────┘
       ┌──────────┐
       │ disabled │  (operator parked — supervisor never touches)
       └──────────┘
```

- `desired_state` is the only column the API mutates for lifecycle. `observed_state` is supervisor-written, server-readable, and **never** accepted in request bodies — the API layer strips it from `PATCH` payloads and 400s if explicitly provided.
- `disabled` is a hard stop: supervisor refuses to start the row even on operator request, until the operator explicitly transitions to `stopped`. This is the parking lot for burned/quarantined collectors.
- `cooling` is a soft backoff between crash and next restart attempt. Duration: `min(2^restart_count, 600)` seconds; capped at 10 minutes. Operator can force-exit cooling via `POST /v1/collectors/{id}/start` (audited as `collector.cooling_overridden`, requires `admin:collectors`).
- `start` and `stop` are **202 Accepted, not 200 OK**. The endpoint sets `desired_state` and returns; the supervisor reconciles on its next tick (≤2s). The UI uses the SSE stream to observe the resulting transition. Pretending these are synchronous would be a lie — and lies in operator software are how people lose evidence.

#### 4.11.3 Identity leasing — exclusive

`Identity` (MODELS.md §2.1) carries `state ∈ {available, in_use, cooling, frozen, burned}`. The supervisor is the single writer of `state=in_use` for collector-bound identities:

1. On collector start: supervisor opens a transaction, asserts `Identity.state = "available"`, sets it to `"in_use"`, writes `Collector.identity_id` (unique constraint enforces one-to-one). Conflict → start fails with `IdentityUnavailable`, collector goes to `crashed` with `last_error_type="IdentityUnavailable"`.
2. On collector stop or crash: supervisor releases the lease — `Identity.state="available"` (or `"cooling"` if `cooldown_seconds > 0`), emits `collector.identity_lease_released`.
3. `admin:collectors` can force-release a lease via `POST /v1/collectors/{id}/force-release-identity` when the supervisor is wedged. Audited heavily. This is the escape hatch, not the happy path.

**No two collectors share an Identity. Ever.** The unique constraint on `Collector.identity_id` is the durable truth. Two simultaneously logged-in Telegram sessions on the same account is how you get banned, and how the operator's OPSEC posture leaks into the platform's anti-abuse signals.

#### 4.11.4 Config — discriminated union, validated, sensitive

`Collector.config` is a JSON blob whose schema is a Pydantic discriminated union on `kind`:

```python
# eyenet/api/v1/schemas/collectors.py — sketch
class TelegramCollectorConfig(BaseModel):
    kind: Literal["telegram"]
    monitor_chat_ids: list[int]
    rate_limit_per_min: int = 60
    proxy_uri_override: str | None = None  # falls back to Identity.proxy_uri

class MatrixCollectorConfig(BaseModel):
    kind: Literal["matrix"]
    monitor_rooms: list[str]
    homeserver_url: str
    initial_sync_limit: int = 100

CollectorConfig = Annotated[
    TelegramCollectorConfig | MatrixCollectorConfig,
    Field(discriminator="kind"),
]
```

`POST` and `PATCH` validate against the union; unknown `kind` is 400. New collector kinds = one new arm in the union + one new collector implementation behind `CollectorBase` (the existing collector abstraction — see CLAUDE.md §4.4). The API surface does not change.

**Sensitivity:** `config` is `restricted` tier by default. The full blob is only returned when the caller has `read:collectors_config`. Without it, `GET /v1/collectors/{id}` returns a redacted form:

```json
{
  "id": "...",
  "instance_name": "tg_alpha_collector_01",
  "kind": "telegram",
  "source_id": "...",
  "identity_id": "...",
  "desired_state": "running",
  "observed_state": "running",
  "last_heartbeat_at": "2026-05-25T14:00:01Z",
  "config": { "kind": "telegram", "__redacted__": true },
  ...
}
```

Rationale: `monitor_chat_ids` and `monitor_rooms` are themselves intelligence — they reveal who EYENET is watching. A `viewer` who can read the chat-ID list can correlate it with public knowledge and infer cases. Treat the config blob the same way we treat any `restricted` evidence: the existence of the collector is `internal`, but its scope is `restricted`.

#### 4.11.5 Lifecycle events — SystemLog, not a third table

Every supervisor-driven transition emits one `SystemLog` row (MODELS.md §2.16) with a curated event name and one `eyenet.audit.collector.*` audit row (MODELS.md §2.14) when operator-initiated:

| Event | SystemLog level | Audit? | Trigger |
|---|---|---|---|
| `collector.created` | `lifecycle` | yes | `POST /v1/collectors` |
| `collector.config_changed` | `lifecycle` | yes | `PATCH /v1/collectors/{id}` (config delta) |
| `collector.started` | `lifecycle` | yes (operator-initiated) / no (supervisor restart) | desired→running transition |
| `collector.stopped` | `lifecycle` | yes (operator-initiated) | desired→stopped transition |
| `collector.crashed` | `error` | no | task raised, supervisor caught |
| `collector.cooling` | `notice` | no | crash → backoff enter |
| `collector.cooling_overridden` | `lifecycle` | yes | `admin:collectors` force-start during cooling |
| `collector.identity_lease_released` | `lifecycle` | yes (force) / no (normal stop) | lease release |
| `collector.deleted` | `lifecycle` | yes | `DELETE /v1/collectors/{id}` |

Operator-initiated audit rows reference the originating `SystemUser.id` and include the collector id in `subject_id` (with `subject_kind="collector"`). The audit chain (§5) makes the operator's intent recoverable; SystemLog makes the supervisor's reality queryable. They are not redundant.

#### 4.11.6 SSE — `/v1/stream/collectors` and `/v1/stream/collectors/{id}`

Bus subjects:
- `eyenet.collector.lifecycle` — fleet-wide; one envelope per state transition.
- `eyenet.collector.lifecycle.{collector_id}` — per-instance, suffix-matched for the scoped stream.
- `eyenet.collector.heartbeat.{collector_id}` — periodic (default 30s); proves the task is alive between transitions.

Envelope shape (bus-side):
```json
{
  "event": "collector.crashed",
  "collector_id": "01HZ...",
  "kind": "telegram",
  "from_state": "running",
  "to_state": "crashed",
  "error_type": "FloodWaitError",
  "error_message": "A wait of 86400 seconds is required",
  "occurred_at": "2026-05-25T14:00:00Z",
  "trace_id": "...",
  "span_id": "..."
}
```

The SSE replay rules (§6.2) apply unchanged. Fleet dashboard subscribes to the wide stream and renders the table; the collector detail panel subscribes to the narrow stream and gets heartbeats too.

#### 4.11.7 Why this is in §4 and not §3

§3 is the surface map — the table of contents. §4 is the contract that makes the surface enforceable. Collectors get their own §4 subsection because:

1. Identity leasing crosses two storage tables transactionally and has a force-release escape hatch with its own audit shape.
2. Config sensitivity intersects §4.7 tiers (redaction depends on a grant-only scope).
3. The supervisor process model is part of the API contract — `start`/`stop` are 202-not-200 because the supervisor is the actual actor, and the SSE stream is the only honest place to learn the outcome.

None of that fits in a surface-map row.

### 4.12 Candidates — the recursive discovery loop

`GroupCandidate` (MODELS.md §2.20) and `GroupCandidateMention` (§2.21) are the substrate of the discovery loop: collectors observe cross-references to groups EYENET is not yet in, those references aggregate into candidates, and the operator triages — manually, or via per-Case auto-join policy. §4.12 is the contract that makes this loop **operator-supervised by default, OPSEC-aware in execution, and recoverable when it goes wrong**.

#### 4.12.1 Posture — hybrid by default

The system ships with `Case.auto_join_policy = disabled` for every new Case. Every candidate is operator-triaged in the UI. Auto-join is opt-in per Case, and the threshold is configured per Case — there is no system-wide default that auto-joins anything.

Rationale: "we joined this group" is a court-defensible act under the §2.13 `EngagementAuthorization` framework. The audit row attributing the join to either a SystemUser (manual approve) or to the policy row in effect at that moment (auto approve) must be reconstructable. Defaulting to disabled means the operator has to consciously opt in to automation per investigation — there is no setting in `eyenet.toml` that quietly enables auto-expansion across the fleet.

#### 4.12.2 Discovery → score → queue

The `channel_reference_extraction` sensor primitive (sensor module, not modeled here) runs on every Message. For each detected reference to an unobserved group:

1. **Resolve-or-create the candidate.** Storage: `INSERT INTO group_candidate (source_id, platform_groupid, ...) ON CONFLICT (source_id, platform_groupid) DO NOTHING`. Either way, retrieve the row.
2. **Append the mention.** `INSERT INTO group_candidate_mention (...)` — never upserted; every observation is its own row. The mention carries `observed_by_collector_id`, `observed_in_group_id`, `seed_root_id`, `depth_from_root`, `mentioning_actor_id`, `mention_kind`.
3. **Recompute the score.** Server-side function (`score_candidate(candidate_id)`); writes back to `GroupCandidate.score` + `score_breakdown`. Inputs: `distinct_mentioning_groups`, `distinct_mentioning_actors`, time-decayed recency, role-signal boost from `mentioning_actor_role_signal` snapshots.
4. **Auto-queue threshold.** If `state = discovered` and the new score crosses the Case (or Source-default) `auto_join_score_threshold`, transition to `queued` and emit `candidate.queued`. The candidate now appears in the operator's triage view.
5. **Auto-approve gate** (only when `auto_join_policy != disabled` for at least one Case containing a mention's `seed_root_id`): evaluate `auto_join_policy` AND eligibility (§4.12.3). If both pass, transition `queued → approved` and emit `candidate.auto_approved` with the originating policy row id frozen in the audit payload.

The score function is **deterministic and frozen per release**. Changing it bumps a `score_function_version: int` column on `GroupCandidate` and is itself an audit event (`candidate.score_function_upgraded`). The operator must be able to reconstruct "why was X auto-approved on Tuesday" against the score function in effect on Tuesday, not today's.

#### 4.12.3 Eligibility — per-collector, computed at decision time

Before approving (manual or auto), the server computes per-collector eligibility against the candidate. The predicate combines provenance from MODELS.md §2.21 (`GroupCandidateMention.depth_from_root`) with active-membership state from MODELS.md §2.22 (`CollectorGroupMembership` — the dedup/dual-cover oracle). When two collectors end up in the same group despite the predicate, the per-message dual-sighting record is MODELS.md §2.23 (`MessageObservation.was_first_sighting`), which is what the candidate's `dual_cover_count` field is materialized from. Concrete form:

```python
# eyenet/services/discovery/eligibility.py — sketch
async def eligibility(candidate: GroupCandidate, collector: Collector) -> EligibilityResult:
    # 1. Dedup: is any active collector already in the target group?
    if candidate.resulting_group_id is not None:
        active = await storage.list_active_memberships(group_id=candidate.resulting_group_id)
        if active:
            case = await resolve_case_for_candidate(candidate)
            if case.redundancy_policy == "prefer_single":
                return EligibilityResult.SKIP_DUAL_COVER
            if case.redundancy_policy == "prefer_dual" and len(active) >= 2:
                return EligibilityResult.SKIP_DUAL_COVER

    # 2. Depth: does any mention's seed_root reach this collector at acceptable depth?
    reachable = await storage.reachable_roots_for_collector(collector.id)
    min_depth = min(
        (m.depth_from_root for m in candidate.mentions if m.seed_root_id in reachable),
        default=None,
    )
    if min_depth is None:
        return EligibilityResult.NO_REACHABLE_ROOT
    if min_depth >= collector.config.max_auto_join_depth:
        return EligibilityResult.OVER_DEPTH

    # 3. Identity availability for scout-first policy.
    if not await identity_pool.has_available_scout(source_id=candidate.source_id):
        return EligibilityResult.NO_SCOUT_AVAILABLE

    return EligibilityResult.OK
```

`GET /v1/candidates/{id}` precomputes eligibility against every collector the caller can see and returns it inline:

```json
{
  "id": "01HZ...",
  "source_id": "...",
  "platform_groupid": "-1001234567890",
  "state": "queued",
  "score": 0.78,
  "score_breakdown": { ... },
  "eligibility_per_collector": [
    {"collector_id": "01H...A", "result": "ok"},
    {"collector_id": "01H...B", "result": "over_depth", "min_depth_via_roots": 3, "max_auto_join_depth": 2},
    {"collector_id": "01H...C", "result": "skip_dual_cover"}
  ],
  "mentions": [ ... up to last 50 ... ],
  "mentions_total": 142
}
```

The UI's "Approve & assign to..." dropdown only enables `result: "ok"` collectors. `admin:candidates` can force-bypass `over_depth` and `skip_dual_cover` with explicit override audit events (`candidate.depth_override`, `candidate.dual_cover_override`).

#### 4.12.4 Approval → supervisor command channel

`POST /v1/candidates/{id}/approve` does NOT make the collector join. It transitions state, sets `assigned_collector_id`, and emits `candidate.approved` to the bus. The `CollectorSupervisor` (§4.11.1) subscribes to `eyenet.candidate.approved` and translates it into a typed command on the assigned collector's command channel:

```python
# eyenet/services/collector_supervisor.py — discovery extensions
class JoinGroupCommand(BaseModel):
    kind: Literal["join_group"]
    candidate_id: UUID
    platform_groupid: str
    access_artifact_id: UUID           # the artifact the supervisor selected (MODELS.md §2.24)
    use_scout_identity: bool = True    # supervisor leases a scout from the pool

class LeaveGroupCommand(BaseModel):
    kind: Literal["leave_group"]
    group_id: UUID
    reason: str
```

The supervisor selects `access_artifact_id` BEFORE dispatching the command (selection algorithm in MODELS.md §2.24). The backend receives both the candidate and the chosen artifact, and dispatches the platform API call that matches the artifact's `kind`:

| Artifact kind | Telegram backend call | Matrix backend call |
|---|---|---|
| `public_identifier` | `JoinChannelRequest(InputChannel @ resolve(value))` | `room_join(alias=value, via=details.via_servers)` |
| `invite_link` | `ImportChatInviteRequest(hash from value)` | `room_join(room_id from matrix.to, via=details.via_servers)` |
| `qr_code` | resolve to embedded invite_link, then as above | same |
| `direct_invite` | unsupported via auto — supervisor refuses; queues operator action | `room_join(room_id)` when an inviter member exists; else refuse |
| `paid_subscription` | requires `admin:candidates` override; subscription gate is operator-only | n/a |
| `access_blocked` | always refuse | always refuse |
| `restricted_other` | requires `admin:candidates` override; operator decides | requires override |

Each collector kind owns its own retry, backoff, and platform-error mapping. A Telegram `FloodWaitError` translates to `candidate.failed` with `last_error_type = "FloodWaitError"` and the wait duration in `last_error_message`; the candidate is parked, not retried. An `InviteHashExpiredError` writes the artifact's `validation_state = "expired"` and re-runs artifact selection — if another valid artifact exists for the same candidate, the supervisor tries again with that one in the same tick. **Re-validation is automatic; re-attempt is bounded** (one retry per artifact-selection cycle, never an infinite loop over a candidate's artifact set).

State transitions written by the supervisor:
- `approved → joining` — command dispatched
- `joining → joined` — platform confirmed; supervisor creates the `Group` row with `discovered_via_candidate_id` populated, writes `CollectorGroupMembership(joined_via="candidate")`, sets `GroupCandidate.resulting_group_id`
- `joining → failed` — platform refused or timeout; supervisor writes `last_error_*` fields on the candidate, NOT on the collector (the collector is healthy; only this one join failed)
- `joined → parked` — operator-initiated leave or supervisor-detected ban (e.g. the collector starts seeing 403s on this group); supervisor closes the `CollectorGroupMembership` row (`left_at`, `left_reason`)

#### 4.12.5 Scout identities — graduation flow

When the supervisor picks an identity for a candidate join, it prefers `Identity.role = scout`. The scout joins, EYENET observes for `Source.scout_observation_window_days` (default 7). If during that window:

- No bans, no anti-spam flags, no `FloodWait` storms, no platform-level account warnings → emit `identity.graduated`, set `Identity.role = monitor`, `Identity.graduated_at = now`. The collector continues using the same identity; it is now a monitor.
- Any of the above → emit `identity.burned`, set `Identity.state = burned` and `Identity.role = quarantine`. The candidate goes to `parked`. The operator must triage manually.

This isolates new joins behind disposable identities. A scout that gets burned costs the operator one credential; a monitor that gets burned costs the operator continuity on every group it was already in.

#### 4.12.6 SSE events — `/v1/stream/candidates`

Bus subjects:
- `eyenet.candidate.lifecycle` — fleet-wide; one envelope per state transition.
- `eyenet.candidate.lifecycle.{candidate_id}` — per-candidate.
- `eyenet.candidate.queued` — fan-out to the operator triage UI when a new candidate is ready for review.

Envelope shape:
```json
{
  "event": "candidate.queued",
  "candidate_id": "01HZ...",
  "source_id": "...",
  "platform_groupid": "-1001234567890",
  "display_name_hint": "Rutify Premium",
  "score": 0.78,
  "score_delta_since_last": 0.21,
  "from_state": "discovered",
  "to_state": "queued",
  "case_ids": ["01H...A", "01H...B"],
  "occurred_at": "2026-05-25T14:00:00Z",
  "trace_id": "...",
  "span_id": "..."
}
```

`case_ids` lists every Case whose seed-root subtree contributed a mention — the dashboard uses this to route the candidate notification to the right operator pane. SSE replay rules (§6.2) apply.

#### 4.12.7 Auditing — what lands where

Every transition writes BOTH a SystemLog row (queryable in the UI) AND an audit row (court-defensible chain), with the established split:

| Event | SystemLog level | Audit | Notes |
|---|---|---|---|
| `candidate.discovered` | `notice` | no | first mention landed; high-volume, SystemLog only |
| `candidate.queued` | `lifecycle` | no | score crossed threshold; operator-visible signal |
| `candidate.approved` | `lifecycle` | yes | reason in payload: `manual:<system_user_id>` or `auto:<policy_id>` |
| `candidate.rejected` | `lifecycle` | yes | reason text required |
| `candidate.auto_approved` | `lifecycle` | yes | frozen snapshot of the policy row in effect |
| `candidate.depth_override` | `lifecycle` | yes | `admin:candidates` forced join past depth limit |
| `candidate.dual_cover_override` | `lifecycle` | yes | `admin:candidates` forced second collector into a group |
| `candidate.joined` | `lifecycle` | yes | resulting `group_id` in payload |
| `candidate.failed` | `error` | no | platform-side failure; not operator action |
| `candidate.parked` | `lifecycle` | yes | operator-initiated leave or supervisor-detected ban; reason required |
| `candidate.retry` | `lifecycle` | yes | `admin:candidates` retry on `failed` |
| `candidate.score_function_upgraded` | `lifecycle` | yes | release event; once per deploy |
| `case.seed_roots_changed` | `lifecycle` | yes | changes downstream candidate eligibility |
| `case.root_promoted` | `lifecycle` | yes | interior group promoted; resets depth-from-root for descendants |
| `identity.graduated` | `lifecycle` | yes | scout → monitor |
| `identity.burned` | `error` | yes | scout or monitor went to quarantine |

The `candidate.discovered` firehose stays out of the audit table on purpose — there is no operator action and no SystemUser to attribute. SystemLog filtering by `event = "candidate.discovered"` and date range is the operator's "show me the discovery surface" query.

#### 4.12.8 What this does NOT model (yet)

- **Cross-source bridging** — a Telegram channel that mentions a Matrix room. The Pydantic-discriminated `mention_kind` allows future `bridge_to_other_source` values; the per-collector eligibility predicate already filters on `candidate.source_id == collector.source_id`, so cross-source candidates are correctly inert until a future milestone adds an `IdentityBridge` resolver. Deferred.
- **Public actor-bio scraping for invite links** — discovering a group via an actor's profile bio rather than a sent message. The current substrate is message-only. Adding it = new `mention_kind = "bio_link"` (already in the enum) + a new sensor primitive `actor_bio_reference_extraction`. Model is ready; implementation is deferred.
- **Negative signals** — actors warning each other AWAY from a group ("don't join, it's a honeypot"). Future score function input. Model: an enum extension `mention_kind = "negative_reference"` and a sign-aware score function. Deferred.

### 4.13 Sources & SourceDomains — the platform registry

`Source` (MODELS.md §1.1) and `SourceDomain` (§2.26) are the operator-curated platform registry. Every Collector points at a Source; every cross-source URL artifact (§2.7) resolves against the SourceDomain index. Mutation here is **load-bearing for the discovery loop and the cross-source bridge** — getting it wrong silently breaks resolution for every artifact ingested afterward.

#### 4.13.1 Posture

- **Operator-only.** No system path creates Sources or SourceDomains automatically. The bridge resolver (§2.25) populates `InfrastructureArtifact.resolved_to_source_id` automatically once a matching Source exists, but the matching Source itself ALWAYS comes from operator intent — never from an inferred-domain promotion.
- **Inline invariants, not async jobs.** The storage layer's writes for Source / SourceDomain trigger MODELS.md §2.25 resolution sweeps in-transaction. By the time the API returns 2xx, every affected `InfrastructureArtifact` row has been re-evaluated. The UI can refresh and show the new resolution counts immediately. No polling, no queue.
- **`canonical_url` is a derived invariant, not an independent field.** PATCHing `canonical_url` requires it to match the current primary SourceDomain's `pattern` per MODELS.md §1.1. Swapping the primary via `PATCH /v1/sources/{id}/domains/{domain_id}` with `{is_primary: true}` triggers re-validation; the swap response includes a `canonical_url_status` field with values `ok`, `now_invalid` (server null-ed it), or `updated` (server rewrote it — only when the request included `?update-canonical-url=true`).

#### 4.13.2 Overlap conflicts — 409 with structured payload

`POST /v1/sources/{id}/domains` runs MODELS.md §2.26's `_scan_overlaps` BEFORE inserting. On conflict, response is HTTP 409 with problem+json:

```json
{
  "type": "https://eyenet.local/errors/source-domain-overlap",
  "title": "SourceDomain overlap",
  "status": 409,
  "detail": "Pattern 'forum.example.com' (exact) conflicts with existing patterns on other Sources",
  "conflicts": [
    {
      "other_source_id": "01H...",
      "other_source_display_name": "Example Network",
      "other_pattern": "*.example.com",
      "other_pattern_kind": "subdomain_wildcard",
      "why_overlap": "new exact pattern falls under existing wildcard's subdomain space"
    }
  ],
  "force_available": true,
  "force_required_scope": "admin:sources"
}
```

The UI presents the conflict to the operator with a clear "Force anyway (marks both ambiguous)" affordance that's disabled unless the caller has `admin:sources`. The force path retries with `?force=true` and writes the `source_domain.overlap_forced` audit row.

#### 4.13.3 Bulk Source creation — atomic, per-Source

`POST /v1/sources` with a `domains: [...]` array creates the Source AND every SourceDomain in one transaction. The validation is "as if added one-by-one": overlap detection runs against the existing DB state plus each prior row in the same payload. If ANY row would conflict, the whole transaction rolls back and the response is the standard 409 payload pointing at the FIRST conflict encountered. There is no "partial success" mode — either the entire Source materializes correctly, or nothing changes.

Rationale: operator-facing bulk-add is an atomic intent ("set up the forum with these three mirror domains"). A half-created Source with two of three intended domains is operationally worse than no Source — the bridge resolver would resolve some artifacts against an incomplete pattern set and the operator would never know.

#### 4.13.4 Deletion semantics — Source vs SourceDomain

**SourceDomain deletion is soft-by-default.** `DELETE /v1/sources/{id}/domains/{domain_id}` writes `removed_at` and an audit event; the row is excluded from future matching but preserved for audit reconstruction. Historical `InfrastructureArtifact.resolved_to_source_id` rows that were set via this SourceDomain keep their FK intact — the FK references the Source, not the SourceDomain row. New artifacts mentioning the removed pattern go `unresolved` per §2.25, which is correct.

`?hard=true` requires `admin:sources` and drops the row outright. Use case: typo correction immediately after add, before any artifacts resolved through it. Refuses with 409 if ANY `InfrastructureArtifact` exists whose `resolved_to_source_id` was set during this SourceDomain's active lifetime — the audit chain depends on the row's existence to reconstruct "why did this artifact resolve to this Source on date X." Hard-delete is for "this never should have been added," not for "this is no longer relevant."

**Source deletion is refused while in use.** `DELETE /v1/sources/{id}` refuses (409) while:
- any `Collector.source_id` references it (collectors must be reassigned or deleted first), OR
- any `InfrastructureArtifact.resolved_to_source_id` references it (artifacts must be unresolved manually or via `?force=true`), OR
- any `GroupCandidate.source_id` references it (candidates must be rejected or transitioned to a different Source first; the latter is rare and admin-only).

`?force=true` requires `admin:sources` and:
1. Reassigns every dependent Collector to a sentinel `parked` Source (creating it if missing).
2. SET NULL on every dependent `InfrastructureArtifact.resolved_to_source_id`, writes `infrastructure.unresolved_post_source_delete` audit per row (bounded — for typical operators the set is small; for a Source with millions of resolved artifacts, the operation is rejected unless `?force=true&i-know-what-im-doing=true` per the explicit-consent convention).
3. Soft-deletes every SourceDomain row.
4. Marks the Source itself with `deleted_at` (extension to §1.1 — Source soft-delete; rows retained for audit) rather than a hard DELETE.

Hard DELETE of a Source is NOT exposed via API. If the operator needs it (testing, mistaken creation immediately reversed), `eyenet source purge <id>` CLI is the path, and it refuses if ANY downstream row references the Source. Forensic-grade evidence systems do not let operators erase the configuration history through which evidence was collected.

#### 4.13.5 SSE — no dedicated subject

Source and SourceDomain mutations are infrequent (operator-pace, not collector-pace), so no dedicated SSE subject. Affected dashboards subscribe to `eyenet.audit.lifecycle` and filter on the relevant event names: `source.created`, `source.updated`, `source.deleted`, `source_domain.added`, `source_domain.removed`, `source_domain.primary_changed`, `source_domain.overlap_forced`, `infrastructure.resolved_on_ingest`, `infrastructure.bridge_resolved_existing_artifacts`, `infrastructure.ambiguous_on_ingest`, `infrastructure.resolution_revoked`, `infrastructure.resolved_post_source_change`, `infrastructure.unresolved_post_source_delete`.

The audit-event stream is the right surface here because these are inherently low-volume, operator-correlated changes — adding an SSE subject just for Sources would burn complexity for no value.

#### 4.13.6 Auditing — what lands where

| Event | SystemLog level | Audit | Notes |
|---|---|---|---|
| `source.created` | `lifecycle` | yes | includes initial SourceDomain set if bulk |
| `source.updated` | `lifecycle` | yes | `display_name` / `canonical_url` / `notes` deltas |
| `source.deleted` | `lifecycle` | yes | soft-delete; `force` flag noted in payload |
| `source_domain.added` | `lifecycle` | yes | |
| `source_domain.overlap_forced` | `error` | yes | `admin:sources` overrode overlap; both sides ambiguous now |
| `source_domain.removed` | `lifecycle` | yes | soft by default; `hard` flag in payload when used |
| `source_domain.primary_changed` | `lifecycle` | yes | includes old + new primary, canonical_url disposition |
| `infrastructure.*` events (§2.25) | various | yes | already covered in MODELS.md §2.25; emitted by storage-layer resolution sweeps triggered by these endpoints |

The bridge-resolution audit events ride on the same chain as the source-mutation events that triggered them — a single audit walk recovers "operator added domain X at time T → 47 artifacts resolved → 3 became ambiguous" as a contiguous run with a shared `trace_id`.

#### 4.13.7 What this does NOT model

- **Programmatic SourceDomain discovery.** No endpoint accepts "we observed this domain a lot — auto-suggest it as a SourceDomain for an existing Source." The discovery-suggestion flow lives in the Infrastructure UI (`GET /v1/infrastructure?resolution_state=pending_source`) and the operator manually decides whether to add. Auto-suggestion would invert the operator-only posture.
- **Source merging.** "I configured two Sources for the same forum by mistake, merge them." Future tooling, manual migration script. Not API-exposed yet — too easy to get wrong, too rare to design pre-emptively.
- **Source-level rate limits / quotas.** A Source might have global rate limits across all Collectors observing it. Modeled at the Collector level today (per-collector `rate_limit_per_min`); a Source-level aggregate ceiling is a sensible future addition. Deferred.

---

## 5. Audit contract

The single most important section of this document.

### 5.1 Read audit

Every endpoint that dereferences evidence (the `evidence_access` column above) emits exactly one `eyenet.audit.evidence_access` row per dereferenced subject, **before returning the response body**.

**The gate is the audit STORAGE WRITE, not the bus publish.** See §5.5 for the unified durability rule. If the durable audit append fails, the request fails with 503 and no data is returned.

```
subject: eyenet.audit.evidence_access
{
  "user_id": "<uuid>",
  "subject_type": "actor" | "persona" | "linkage" | "observation",
  "subject_id": "<uuid>",
  "endpoint": "/v1/actors/{actor_id}",
  "method": "GET",
  "request_id": "<uuid7>",
  "trace_id": "<32-hex>",     // §11.3 cross-link
  "span_id":  "<16-hex>",
  "client_ip": "10.0.0.42",
  "user_agent": "...",
  "ts": "2026-05-24T12:34:56Z"
}
```

Bulk endpoints (e.g. `/observations`, `/timeline`) emit one row per returned subject. This is operator-grade evidence; the cost is acceptable.

### 5.2 Write audit

Every write emits `eyenet.audit.operator_action` BEFORE publishing the bus event. The gate is again the durable audit append (§5.5): if the audit row is not safely persisted to the hash chain, the operator action does not happen and the bus event is never published.

```
subject: eyenet.audit.operator_action
{
  "user_id": "<uuid>",
  "action": "linkage.confirm" | "linkage.reject" | "identity.claim" | ...,
  "target_type": "linkage" | "identity" | ...,
  "target_id": "<uuid>",
  "request_id": "<uuid7>",
  "trace_id": "<32-hex>",     // §11.3 cross-link
  "span_id":  "<16-hex>",
  "idempotency_key": "<client-supplied or null>",
  "client_ip": "...",
  "user_agent": "...",
  "ts": "..."
}
```

### 5.3 Auth audit

```
subject: eyenet.audit.auth
{
  "user_id": "<uuid> or null on failed login",
  "event": "login.success" | "login.failure" | "refresh" | "logout" | "token.minted" | "token.revoked",
  "trace_id": "<32-hex>",     // §11.3 cross-link
  "span_id":  "<16-hex>",
  "client_ip": "...",
  "user_agent": "...",
  "reason": "wrong_password" | null,
  "ts": "..."
}
```

### 5.4 Audit-read does not audit itself

`GET /v1/audit` and `GET /v1/audit/verify` do NOT emit `evidence_access`. They emit a single `eyenet.audit.audit_query` row, which is itself part of the chain. This prevents recursive amplification.

### 5.5 Durability rule — storage is the gate, bus is fan-out

The audit hash chain has exactly one source of truth: the durable audit-store append (`BEGIN IMMEDIATE`-serialized per PLAN §542). The bus publish is best-effort fan-out for live consumers (SSE subscribers, sister services). The two cannot get out of sync because the storage write is what every consumer ultimately reconciles against.

Concretely, every audit emission (read, write, auth, audit-query) follows the same sequence:

1. **Persist** the audit row to the hash chain. This is the gate. Failure → 503 to the client; no further work happens; no bus message is published.
2. **Mark `bus_published_at = NULL`** on the freshly-appended row.
3. **Publish** the matching `eyenet.audit.*` envelope on the bus, asynchronously. On ack, update `bus_published_at`. On failure, leave NULL; a background retry walks unpublished rows in chain order and republishes with bounded backoff.
4. For **write endpoints only**, the bus publish of the actual domain event (`attribution.linkage.confirmed`, `eyenet.identity.claimed`, …) happens AFTER step 1 succeeds. If the domain bus publish fails, the row stays in the chain with a paired `bus_published_at = NULL` on the `operator_action` row, and the same retry walker republishes both in order. **The chain is never a lie**: if an `operator_action` row exists, the operator's intent was durably recorded, and the system is responsible for delivering the corresponding domain event eventually.

Consequences:

- `audit_publish_failures_total` (§11.7) measures *bus* publish failures only — they degrade SSE liveness, never durability.
- Replay sources (§6.2) work entirely off the durable chain; a bus outage during a write does not produce a phantom event downstream because the domain bus event is only emitted after the audit append succeeds.
- `GET /v1/audit/verify` reads the durable chain; it does not depend on bus health.

This is the same gate the CLI already uses today; the API does not introduce a parallel path.

### 5.6 File access journal — every byte of evidence content

The §5.1 read audit logs row dereferences. That is not sufficient when the row contains, or links to, a binary attachment that the operator's machine renders, downloads, or pipes to disk. Heavy-hitter collectors WILL pull in attachments that carry NATO markings, passport scans, leaked dossiers — files whose mere opening is a regulated act under multiple jurisdictions. Logging the row but not the byte stream leaves operators legally exposed; this subsection closes that gap.

**Scope:** every endpoint that serves or could serve binary content from `Observation.attachment_blob_id`, `Message.attachment_blob_id`, or any future blob reference. The journal is the **single point of truth** for "did anyone on this deployment open this file."

**Storage table** `file_access_journal` (lives in the same SQLite file as `audit_log_event` to share the §5.5 durability gate):

| Column | Type | Notes |
|---|---|---|
| `access_id` | UUID7 | Primary key. Referenced from `evidence_access.*` audit rows when the dereference involved bytes. |
| `audit_event_id` | UUID7 | FOREIGN KEY → `audit_log_event.id`. The paired audit row that authorized this access (§5.1 / §5.6 emission). |
| `user_id` | UUID | The accessor. |
| `grant_id` | UUID, nullable | Authorizing clearance grant if the content was `restricted` or `classified` (§4.8). Mandatory when `tier != normal`. |
| `content_hash` | bytes(32) | SHA-256 of the served bytes. Indexed. The exoneration query key. |
| `content_size` | int64 | Bytes served. |
| `content_mime` | text | Server-detected media type at access time. |
| `tier` | enum | `normal`, `restricted`, `classified` — frozen from the row at access time. |
| `served_at` | datetime | Server clock at first-byte. |
| `served_via` | enum | `inline_json` (small text content embedded in response), `attachment_stream` (binary download), `thumbnail_only` (preview, body redacted). |
| `acknowledgment_id` | UUID, nullable | FOREIGN KEY → `file_access_acknowledgment.id`. Mandatory when `tier != normal`. |
| `operator_signature` | bytes(64) | Ed25519 signature over the canonical request form (§5.7). Mandatory on every row, no exceptions. |
| `signing_pubkey_fingerprint` | bytes(8) | `sha256(verifying_key_DER)[:8]` — disambiguates the operator's key version at access time. |
| `prev_journal_hash` | bytes(32) | Chain link. |
| `self_hash` | bytes(32) | `sha256(canonical_serialization_of_this_row || prev_journal_hash)`. The §5.5 storage write gate applies to this chain too. |

**Two-step access flow for `restricted` / `classified` attachments — server-enforced friction:**

1. **Manifest request** (`GET /v1/attachments/{blob_id}/manifest`, scope `read:observations`): returns a `FileManifest` envelope — no bytes — containing `content_hash`, `content_size`, `content_mime`, `tier`, `source_subject_id`, `collected_at`, and a server-issued `access_nonce` (UUID7, 60s TTL, single-use). This is the only way an operator can find out what a file contains without committing.
2. **Acknowledged fetch** (`POST /v1/attachments/{blob_id}/access`, scope `read:<tier>`): body is a `FileAccessAcknowledgment`:
   ```json
   {
     "access_nonce": "<from manifest, single-use>",
     "expected_content_hash": "<sha256 from manifest>",
     "reason": "<≥16 chars, free text justifying THIS specific access>",
     "viewing_context": "case=APT-29-2026Q2|incident=INC-001|...",  // free text
     "operator_signature": "ed25519:<base64sig over the canonical form>"
   }
   ```
   Server validates: nonce live + matches blob, expected hash matches the current blob hash, operator's `read:<tier>` scope is active, the `operator_signature` verifies against `system_user.signing_pubkey`. **Only then** does it persist the acknowledgment row, append the journal row, and begin streaming bytes. Streaming aborted mid-way still leaves the journal row — partial reads count.

For `tier = normal` content the two-step is collapsed: the journal row is still appended (every byte is logged) and the operator signature is still required, but no acknowledgment row and no nonce dance. Friction proportional to sensitivity.

**Bulk-list endpoints never serve binary bodies.** A `/v1/actors/{id}/observations` page returns redaction markers and manifest pointers for any row with non-empty attachments; opening the file is always a separate, individually-acknowledged, individually-journaled act. There is no "I scrolled past it by accident."

**`evidence_access.*` audit rows that involved a byte stream MUST carry `file_access_id`** in their payload. A `restricted`/`classified` `evidence_access` row with no `file_access_id` is a contract violation; the endpoint must fail closed with 503 (mirrors the §4.8 `grant_id` rule).

### 5.7 Operator signing keys — non-repudiation

A stolen bearer token grants the thief the operator's normal scope. That is **not enough** to authorize a file access under §5.6, because every journal row carries an `operator_signature` and the operator's private signing key is never on the wire.

**Per-operator long-term keypair:**

- **Algorithm:** Ed25519. Public key 32 bytes, signatures 64 bytes — small enough to embed in every request without bloat.
- **Generation:** server-side at first login, OR client-side and uploaded — operator's choice, recorded in the audit row that mints the pubkey. Server-side is the default for v1 to keep operator UX simple; client-side is the M9.5+ option for operators who run their own HSM.
- **Storage of the private key (server-side mode):** `<data_dir>/operator_keys/<user_id>.priv.enc` — Ed25519 seed encrypted with `ChaCha20-Poly1305`, key = `argon2id(password, salt=user_id, m=64MiB, t=3, p=1)`. Mode 0600. The server NEVER stores or caches the plaintext seed.
- **Storage of the public key:** `system_user.signing_pubkey` (32-byte column) + `signing_pubkey_set_at`. **Immutable after first set.** Rotation requires `admin:users` + a fresh audit row with `event=signing_pubkey.rotated`; the prior pubkey is moved to `system_user_signing_pubkey_history` so old journal rows remain independently verifiable.
- **At login:** the password is received, argon2id-derived to the KEK, the private seed is decrypted IN MEMORY, used to derive the Ed25519 keypair, and the seed is wiped (`secrets.compare_digest` style zeroize). The keypair instance is held in the session's in-memory state for the duration of the session ONLY. Refresh-token use re-decrypts; the original password is required to bring the key online after a process restart.
- **At logout / session expiry:** the in-memory keypair is dropped. Subsequent signing requires re-auth.

**Canonical request form for signatures:**

```
EYENET-SIG-v1
<METHOD>
<URL-path-with-query>
<X-Request-Id>
<RFC3339-UTC-timestamp>
<sha256-hex of canonical body, or empty-string sha256 if body absent>
<content_hash-being-acknowledged, or empty>
```

Header transmission: `X-Operator-Signature: EYENET-SIG-v1 ed25519=<base64sig>; kid=<8-hex>`.

Server-side verification: reconstruct the canonical form server-side from the received request, look up `system_user.signing_pubkey` (or history if `kid` is older than current), verify with libsodium / `cryptography.hazmat.primitives.asymmetric.ed25519`. Failure → 401 with `problem.title="invalid_signature"`. The journal row is NEVER appended on verification failure; the failed verification itself emits an `eyenet.audit.auth` row with `event=signature.verification_failed` for forensic completeness.

**What this defeats and what it does not:**

- ✅ Stolen JWT: cannot sign — useless against §5.6 endpoints.
- ✅ Stolen access cookie / session fixation: same.
- ✅ Hostile server-side process reading session state: requires the operator's plaintext password to extract the seed; the in-memory keypair lives only inside the request-handler frame, not in any cache. (Limit: a fully-compromised host with kernel access can dump process memory mid-request. Document, don't solve at v1.)
- ✅ "Wasn't me, I lost my token": rebutted — the journal carries a signature only the password-holder could produce.
- ⚠️ "I was forced to enter my password at gunpoint": NOT solvable cryptographically; coercion is a physical-security concern. The operator's defense in that case is that the access pattern (volume, time, content type) is anomalous and is itself observable in the journal, supporting a duress claim. EYENET does not pretend to defeat duress — it makes duress patterns visible.
- ⚠️ Insider with `admin:users` rotating the pubkey before forging signatures with a key they control: defeated by `system_user_signing_pubkey_history` — every historical pubkey is preserved and journal rows reference the pubkey fingerprint they were signed against. A rotation followed by a new "old" access is detectable post-hoc.

**The contract with the operator:** the system will never produce a journal row attributable to you that you could not have produced yourself. If a journal row carries your `user_id`, it carries an `operator_signature` that only your password and your live key file could have generated. Defending against allegations is reading the journal back to the accuser.

### 5.8 Exoneration — proving a file was NOT accessed

The forensic question that matters more than "who opened this?" is **"did anyone on this deployment open this, and if not, can the system prove it?"** A complete file-access journal makes both answerable in one query.

**Endpoint** `GET /v1/audit/file-access?content_hash=<sha256-hex>` — scope `admin:clearance` (this query reveals access patterns and is itself sensitive).

**Response shape** (`FileAccessExoneration`):

```json
{
  "content_hash": "<sha256>",
  "query_time": "2026-05-24T12:34:56Z",
  "journal_head_at_query": "<sha256 of file_access_journal latest self_hash>",
  "accesses": [
    {
      "access_id": "<uuid7>",
      "user_id": "<uuid>",
      "served_at": "...",
      "grant_id": "<uuid|null>",
      "served_via": "attachment_stream",
      "operator_signature_verified": true,
      "audit_event_id": "<uuid7>"
    }
  ],
  "exoneration_signature": "<server signature over the canonical form below>"
}
```

The `exoneration_signature` is the load-bearing field. It is computed by the EYENET deployment's server keypair (NOT an operator key) over the canonical form:

```
EYENET-EXONERATION-v1
<content_hash>
<query_time>
<journal_head_at_query>
<count of accesses>
<concatenated access_ids in chain order>
```

Properties this gives you:

- **Empty-accesses result is meaningful**: an array of zero, signed by the server against the journal head at a specific time, is a positive cryptographic assertion that **no row referencing `<content_hash>` exists in the journal up to head `<H>` at time `<T>`**. Combined with §5.9 external anchoring, it's a fact a third party can independently verify.
- **Non-empty result enumerates every accessor**: with signatures verifiable per row (§5.7), each access is independently attributable. An organization handed this output can immediately say "of our 12 operators, exactly Alice accessed this file once on 2026-04-11 with grant_id X granted by Bob for reason Y" — and any operator NOT in the list has cryptographic proof they did not access it.
- **Tamper detection**: re-running the query later must return a result where the `journal_head_at_query` has only ADVANCED (the chain is append-only). If a later query returns an earlier head, the journal has been rewound — itself an `eyenet.audit.integrity.alarm` event the system raises during `GET /v1/audit/verify`.

**Companion endpoint** `GET /v1/audit/file-access/by-user?user_id=<uuid>` — scope `admin:clearance` — same envelope shape, returns every file access by a single operator over a `[since, until]` window. The "Alice is leaving the team; what did she touch?" report.

These two queries are the artifact an operator hands to their lawyer. Not a CSV export, not a "trust us we have logs" affidavit — a signed cryptographic statement against a journal head whose integrity is itself externally verifiable (§5.9).

### 5.9 External anchoring — the journal is not just our word

The hash chain (§5.5) and the journal chain (§5.6) are tamper-evident **within the deployment**. They cannot resist a coordinated forge by someone with full filesystem access plus the deployment's server signing key. To raise the bar to "would have to corrupt an external party too," the chain heads anchor outward at fixed intervals.

**Mechanism (v1, minimal):**

- Every 5 minutes, a background task computes `audit_chain_head_hash` and `journal_chain_head_hash`, serializes them with `(deployment_id, anchor_seq, anchored_at)`, signs with the deployment's server key, and appends the record to `<data_dir>/anchors/anchors.log` (append-only file, mode 0600). This file is the local anchor stream.
- The same record is emitted on the bus subject `eyenet.audit.anchor` for any subscriber (including operator-provisioned exporters) to forward to ONE OR MORE external sinks. Built-in sinks for v1:
  - **`file_sink`**: writes to a configurable additional path (often a mounted external volume — operator's offline backup).
  - **`webhook_sink`**: HTTP POST to a configured URL with bearer-auth (e.g. organization-controlled S3 + Object Lock, or the lawyer's `/inbox`).
  - **`email_sink`**: sends the signed anchor record to a configured address (legal counsel, compliance officer).
- M9.6 candidates (not v1 commitments): RFC 3161 TSA submission, Sigstore Rekor entry, blockchain anchor.

**What this buys you:**

A third party (your lawyer, an auditor, a court) who has been receiving anchor records on a regular cadence can, at any later time, independently corroborate that the journal head you present to them was already committed at the time the anchor was received. If the deployment is forced to rewrite history, the anchors that the external party already holds will not match — and that mismatch is provable without needing to trust EYENET at all.

The `Anchor` record schema is its own named OpenAPI component (carried in the `eyenet.audit.anchor` bus subject and exposed via `GET /v1/audit/anchors` for the operator's own audit). Schemathesis fuzzes it like any other surface.

**Operational rule:** if anchor emission fails for >15 minutes, the deployment SHOULD raise an `eyenet.audit.integrity.alarm` event (and Prometheus alert, §11.7). The chain is still durable internally during that window; the alarm is about the external-witness property degrading, not the local journal.

---

## 6. Realtime (SSE)

### 6.1 Wire format

Standard SSE. UTF-8 text. One event per `\n\n`-terminated block:

```
id: 01HABCDE7F8G9H0J1K2M3N4P5Q
event: linkage.proposed
data: {"linkage_id":"...","actor_a_id":"...","actor_b_id":"...","score":0.81,...}

```

- `id:` is the bus event's `uuid7` — used for resume.
- `event:` is the bus subject (last segment, e.g. `linkage.proposed`).
- `data:` is a single line of compact JSON.
- Heartbeat every 15s as a comment line: `: keepalive\n\n`. No event, no id.

### 6.2 Resume / replay

**The API is bus-agnostic.** Replay is NOT a bus-provider feature. It is served from authoritative storage; the bus is used only for live tail. This decouples the API from NATS JetStream (or any other backend) and lets MemoryBus, NATS-core, and any future provider work identically.

The mechanism is a per-stream `StreamReplaySource` (§6.6) that knows how to query the system-of-record table for "events since cursor X." Every stream in scope for v1 has a durable storage representation:

| Stream | Replay source | Storage of record |
|---|---|---|
| `attribution.linkage.*` | `LinkageReplaySource` | `linkage_event_log` (§11.5) — one row per state transition, ordered by `(ts, event_seq)` |
| `attribution.persona.updated` | `PersonaReplaySource` | `persona_event_log` (§11.5) — one row per update |
| `eyenet.audit.*` | `AuditReplaySource` | audit hash chain — already an ordered ID-keyed log |
| `eyenet.control.*` / freeze / panic | `ControlReplaySource` | audit hash chain (filtered by subject prefix) — control actions are always audit-emitting |

On reconnect with `Last-Event-ID: <uuid7>`:

1. The handler invokes `source.replay(after=Last-Event-ID)` and streams the historical events.
2. When the replay iterator drains, the handler switches to `bus.subscribe(subject)` for live tail.
3. The catch-up-to-live boundary is reconciled by tracking the first live message's cursor vs the last replay cursor; any overlap is deduplicated by event id.

If `Last-Event-ID` predates `source.oldest_available()` → emit a single `event: stream.gap\ndata: {"oldest_available":"<cursor>"}` and resume from the oldest available event. Client decides whether to backfill via REST.

For v1 streams nothing is currently garbage-collected, so the `stream.gap` path is defensive — but the protocol-level event stays defined.

### 6.3 Backpressure

Per-connection backpressure is **per-topic**, not a single shared queue. For each subscribed topic family the connection holds an independent bounded queue (default 1024 events) and a writer that drains them in FIFO order, multiplexed onto the single SSE response stream.

This avoids the head-of-line failure mode where one slow / never-dropped topic (e.g. `audit.*`) fills a shared queue and starves every other topic on the same connection.

Per-topic drop policies:

| Topic family | Policy on overflow |
|---|---|
| `eyenet.audit.*` | **Never drop.** If the audit queue fills, the connection is terminated with `stream.terminated{reason:"audit_backpressure"}` and the client must reconnect with `Last-Event-ID` (replay from durable chain). Audit liveness is a per-connection property; correctness is a per-storage property — terminating the connection trades the former for the latter. |
| All other families | Drop oldest. |

On any drop:

- Emit `event: stream.backpressure\ndata: {"topic":"linkages","dropped":N}` once per (topic, 5s window).
- Metrics: `eyenet_api_sse_events_dropped_total{stream, topic, reason}`, `eyenet_api_sse_terminated_total{stream, reason}`. Label set matches the catalog in §11.7.2; `user` is excluded from Prometheus exposition per the cardinality discipline in §11.7.3 (kept on OTLP only).

### 6.4 Auth on SSE

**The constraint.** Browser `EventSource` cannot send custom headers — the WHATWG spec deliberately omits an init-dict for headers. This affects exactly one consumer class: the browser-based operator UI. Every non-browser client (`httpx`, curl, Python SDKs, external integrators via PAT) sends `Authorization: Bearer <token>` on the initial GET normally and is unaffected by the rest of this section.

#### 6.4.1 Browser auth — primary path: fetch-streaming polyfill

The operator UI uses a `fetch()`-based SSE client (e.g. `@microsoft/fetch-event-source` or equivalent) which re-implements the SSE wire protocol on top of `fetch()` and supports arbitrary headers. The UI sends `Authorization: Bearer <access_token>` exactly like REST calls; the server treats SSE auth identically to REST auth. One auth scheme across the entire API.

Trade: ~5 KB of JS in the UI bundle. Accepted.

#### 6.4.2 Browser auth — fallback: stream-token in query string

For deployments where the polyfill path is unworkable (corporate proxies that buffer non-native `EventSource` streams, raw-URL debugging scenarios), an ephemeral stream token can be exchanged out-of-band:

```
POST /v1/auth/stream-token
Authorization: Bearer <access_token>
Body: { "stream": "linkages" }                              # single-stream form
   or { "stream": "all", "topics": ["linkages","audit"] }   # multiplexed form
```

Response: `{ "stream_token": "<jwt>", "expires_in": 60 }`.

The returned JWT has `token_type: "stream"` (§4.2). Its `aud` claim encodes the bound endpoint and (for the `all` form) the exact topic set:

```json
{
  "aud": "/v1/stream/linkages"
}
// or
{
  "aud": "/v1/stream/all",
  "topics": ["linkages","audit"]
}
```

The client then opens either `EventSource("/v1/stream/linkages?token=<stream_token>")` or `EventSource("/v1/stream/all?topic=linkages&topic=audit&token=<stream_token>")`.

Server-side enforcement:

- `token_type: "stream"` tokens are refused on every endpoint except `/v1/stream/*`. They cannot authorize REST reads, writes, refreshes, or anything else even if they leak.
- TTL 60 seconds from mint to first use.
- Single-connection: server records `jti` on connect and refuses reuse. A second connection attempt with the same `jti` returns 401.
- The `aud` claim locks the token to one endpoint path; using it on a different `/v1/stream/*` path returns 401.
- For `/stream/all`, the request's `?topic=...` query set must be **identical to** the token's `topics` claim (set equality, ignoring order). Any drift — extra topic, missing topic — returns 401. Minting the token requires all underlying `stream:*` + `read:*` scopes for every topic; the request-time check is a re-resolution against current scopes (no carve-out — scope cache rule §4.4.1 still applies, but cache eviction on logout terminates the live connection anyway).

Mitigations against URL-leak surfaces (referer, access logs, browser history, CDN logs) are the short TTL + single-use binding + scope restriction. Mitigation is not elimination — this is why §6.4.1 is the primary path and this one is the fallback.

#### 6.4.3 Rejected: httpOnly session cookie

Considered and rejected. Pros: native `EventSource` works without a polyfill. Cons:

- Introduces a second auth scheme alongside Bearer (PAT users still need Bearer).
- Forces CSRF protection across every state-changing endpoint forever, to defend the cookie.
- Doubles the misconfiguration surface for the lifetime of the API to save the UI bundle a one-time ~5 KB.

Net cost-over-time exceeds the polyfill cost. Not adopted.

#### 6.4.4 Connection lifecycle

- **REST-Bearer SSE (§6.4.1):** server tracks the access token's `exp` and closes the connection at expiry. Client reconnects with a refreshed token using `Last-Event-ID` for replay.
- **Stream-token SSE (§6.4.2):** the stream token is consumed on connect. The connection is bound to a **hard ceiling equal to the access-token TTL (15 min)** — regardless of whether scopes change or not. At ceiling the server closes the connection with a `stream.expired` event; the client must obtain a fresh stream token (which requires a still-valid access JWT, per §6.4.2) and reconnect with `Last-Event-ID`. The stream token's own 60s TTL is mint-to-first-use only; the 15-minute ceiling is what bounds the connection itself. This makes the stream-token path symmetric with REST-Bearer SSE: a leaked, already-burned stream token can hold a connection for at most 15 minutes, not indefinitely.
- **Forced revocation:** `POST /v1/auth/logout` and PAT revocation both publish `eyenet.auth.scopes_changed` for the affected `user_id`. All API processes evict the user from the scope cache AND walk their live SSE connections to terminate any belonging to that user. Worst-case revocation latency for SSE is the bus round-trip — well under the §4.4.1 60s cache TTL.

### 6.5 `StreamReplaySource` protocol

Defined in `eyenet/api/v1/stream/_sources.py` (private helper per the §13 layout convention). One implementation per SSE endpoint, registered in a `REPLAY_SOURCES: dict[str, StreamReplaySource]` map keyed by stream name.

```python
class EventCursor(NamedTuple):
    event_id: UUID  # uuid7 — monotonic by ts
    ts: datetime    # sanity check; cursor parses without trusting client ordering


class StreamEvent(NamedTuple):
    cursor: EventCursor
    subject: str             # e.g. "attribution.linkage.confirmed"
    payload: dict[str, Any]  # JSON-serializable


class StreamReplaySource(Protocol):
    """Per-stream historical event source. Reads from authoritative storage."""

    async def replay(self, after: EventCursor) -> AsyncIterator[StreamEvent]:
        """Yield events strictly after `after`, in cursor order."""

    async def oldest_available(self) -> EventCursor | None:
        """Cursor of the oldest event this source can still serve, or None if empty."""
```

`BusClient` keeps the surface it already has: `subscribe(subject) -> AsyncIterator[BusMessage]`. No `subscribe_durable`, no `start_from`. The bus does not know SSE exists.

Backend portability: any bus that can deliver live messages works. MemoryBus (no durability) works because durability lives in storage. NATS-core (no JetStream) works for the same reason. Adding a new bus backend tomorrow requires zero API changes.

### 6.6 Why not WebSocket

- Auth simpler (Bearer header, no subprotocol negotiation).
- One-way fits the model — clients don't push events.
- HTTP/2 + proxy infra friendly. No upgrade-handshake gotchas.
- Reconnect / replay protocol is built into the spec.

Revisit if a future use case needs client-initiated subscribe/unsubscribe on a live socket. Today: separate endpoints + `/stream/all?topic=` filter is enough.

---

## 7. Error contract

All errors return `application/problem+json` (RFC 7807). The envelope is a **declared Pydantic model** (`ProblemDetail` in `eyenet/api/v1/schemas/errors.py`) referenced by every endpoint's `responses=` map, so the OpenAPI schema describes every error shape explicitly. Schemathesis and codegen consume that.

```json
{
  "type": "https://eyenet.local/errors/linkage-not-found",
  "title": "Linkage not found",
  "status": 404,
  "detail": "linkage_id=01HABC... has no row in linkage store",
  "instance": "/v1/linkages/01HABC...",
  "request_id": "01HXYZ...",
  "trace_id": "<32-hex>",
  "errors": []
}
```

```python
# eyenet/api/v1/schemas/errors.py
class ValidationError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    loc: list[str | int]
    msg: str
    type: str

class ProblemDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str           # absolute URI identifying the error class
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str
    trace_id: str | None = None
    errors: list[ValidationError] = []
```

- `request_id` is always present. Comes from `X-Request-Id` header if client supplies one (validated as uuid7-or-uuid4); otherwise minted.
- `errors[]` is used for 422s — array of `{loc: [...], msg: "...", type: "..."}`.
- HTTP status mapping is exhaustive:
  - 400 — malformed request body / bad header
  - 401 — missing or invalid credentials
  - 403 — authenticated but insufficient scope
  - 404 — entity not found
  - 409 — idempotency-key reuse with a different body
  - 422 — schema validation (pydantic)
  - 429 — rate limited
  - 503 — audit publish failure, storage unavailable, bus disconnected

No bare 500s in normal operation. Unhandled exceptions are caught by a top-level middleware that:
1. Logs the exception with `request_id`.
2. Returns `500 problem+json` with `type: https://eyenet.local/errors/internal`.
3. Emits `eyenet.audit.api_error` with the traceback hash (not the traceback itself — that goes to logs).

---

## 8. Pagination

All list endpoints use opaque cursors. No offset.

**Request:**
```
GET /v1/linkages?state=proposed&limit=50&cursor=<opaque>&include_total=1
```

**Response (default, no total):**
```json
{
  "items": [...],
  "next_cursor": "<opaque or null>"
}
```

**Response (with `include_total=1`):**
```json
{
  "items": [...],
  "next_cursor": "<opaque or null>",
  "estimated_total": 1234
}
```

- `cursor` is `base64url(json({"after_id": "<uuid7>", "after_ts": "...", "sort": "..."}))`. Opaque to clients; humans can decode for debugging.
- `estimated_total` is **opt-in** via `?include_total=1`. Filtered `COUNT(*)` is expensive on large tables (especially audit), and most pagination flows do not need a total. When requested, it is best-effort and capped at 10_000 ("10000+"); short-TTL (30s) per-(endpoint, filter-key) cache backs repeated requests so paging through a list does not re-count on every page. Clients use it for UI hints, never for control flow.
- `limit` default 50, max 500.
- Sort order is documented per endpoint and embedded in the cursor; changing the sort restarts pagination.

---

## 9. Schemas / typing

### 9.1 Versioned namespace

```
eyenet/api/v1/schemas/
  __init__.py
  auth.py       # LoginRequest, TokenPair, AccessToken, UserMe,
                # PATSummary, PATMinted, StreamTokenRequest, StreamTokenMinted
  actors.py     # ActorSummary, ActorDetail, NeighborList, ObservationSummary, TimelineEntry
  personas.py   # PersonaSummary, PersonaDetail, PersonaMember
  linkages.py   # LinkageSummary, LinkageDetail, LinkageDecisionRequest
  graph.py      # GraphStats, GraphSearchResult
  audit.py      # AuditRow, AuditVerifyResult
  stream.py     # LinkageProposedEvent, LinkageStateChangedEvent, PersonaUpdatedEvent,
                # AuditEvent, ControlEvent, StreamGapEvent, StreamBackpressureEvent,
                # StreamTerminatedEvent, StreamExpiredEvent
  identities.py # IdentityActionRequest
  writes.py     # WriteAccepted (the §10.3 shared response shape)
  health.py     # HealthStatus, ReadyStatus
  errors.py     # ProblemDetail, ValidationError (§7)
  pagination.py # CursorPage[T] (§8)
```

All `BaseModel` use `model_config = ConfigDict(extra="forbid", populate_by_name=True)`. Every schema class carries a docstring referencing its source in `MODELS.md` where applicable; the §14.4 lint enforces it (§9.5).

### 9.2 Enums in query params

`state`, `edge_type`, `linkage_method`, `audit_event` and friends are typed as enums imported from `eyenet/contracts/enums.py`. Garbage values yield 422 with a clear list of permitted values.

### 9.3 Edge attrs

`NeighborEdge.attrs` becomes a discriminated union by `edge_type`. The union variants are the **edge classes**; each carries a typed `attrs` payload:

```python
class LinkedToAttrs(BaseModel):
    state: LinkageState
    method: str
    score: float
    linkage_id: UUID

class BelongsToPersonaAttrs(BaseModel):
    since: datetime
    via_linkage_id: UUID | None

class LinkedToEdge(BaseModel):
    edge_type: Literal["linked_to"]
    target_id: UUID
    attrs: LinkedToAttrs

class BelongsToPersonaEdge(BaseModel):
    edge_type: Literal["belongs_to_persona"]
    target_id: UUID
    attrs: BelongsToPersonaAttrs

NeighborEdge = Annotated[
    LinkedToEdge | BelongsToPersonaEdge,
    Field(discriminator="edge_type"),
]
```

No more `dict[str, object]`. The OpenAPI schema becomes useful, codegen produces typed clients.

### 9.4 Storage layer — abstract factory, NOT a concrete class

**Read this before touching anything in `eyenet/storage/`.**

The persistence layer is an abstract factory. ABCs live in `eyenet/contracts/storage.py` (`MessageStore`, `ObservationStore`, `LinkageStore`, `AuditStore`, `ClearanceStore`, `CaseStore`, `ReclassificationStore`, ...). Concrete implementations live in `eyenet/storage/` and are named after the backend: `SQLiteAuditStore(AuditStore)`, `SQLiteClearanceStore(ClearanceStore)`, etc. The aggregate `SQLiteStorage(Storage)` in `eyenet/storage/sqlite.py` wires them together.

**Backend selection is runtime-configurable.** The `EYENET_STORAGE_TYPE` environment variable (default `sqlite`) drives the engine factory in `eyenet/storage/engines.py`. The factory dispatches over a `_BACKEND_BUILDERS` dict; adding a new backend (MySQL, MariaDB, Postgres) requires:

1. Implementing concrete `<Backend><Store>Name` classes if any SQL is dialect-specific (the SQLModel/SQLAlchemy Core layer handles most cases automatically).
2. Registering a builder function in `_BACKEND_BUILDERS`.
3. The HTTP handlers, the bus contracts, and the API schemas do not change.

**Two physical databases per deployment** (PLAN §5.2 has the full rationale and history):

- **`main`** — every operational table (cases, clearance grants, observations, attachments, messages, actors, linkages, personas, graph, syslog, profiles, corpus cursors, system users, ...). **Cross-store SQL joins are first-class here.** Atomic multi-row writes span any operational table in one transaction.
- **`audit`** — hash-chained append-only forensic evidence (`audit_log` today; M9.1c adds `file_access_journal`, `file_access_acknowledgment`, `system_user_signing_pubkey_history`). Physically isolated so the forensic record stays tamper-evident even if the operational DB is compromised. Writes only — audit is not a read source for normal queries.

**Implementation discipline — non-negotiable:**

1. **Never write a concrete `SQLite*Store` without its parent ABC.** If the ABC doesn't exist yet, add it to `eyenet/contracts/storage.py` first. Do not write `class SQLiteXyzStore:` as a freestanding class — that's how the v0 codebase ended up with `SQLiteAuditStore` lacking a parent ABC for two milestones. The pattern is `class <Backend><X>Store(<X>Store):`.
2. **Never reference a concrete class from the API layer.** Handlers depend on the ABC type, not the concrete impl: `async def handler(audit: AuditStore = Depends(get_audit_store))`, not `SQLiteAuditStore`.
3. **Never use dialect-specific SQL in `eyenet/models/`.** That layer is SQLModel/SQLAlchemy Core — dialect-portable by construction. CHECK constraints use ANSI SQL only (`length(...)`, comparison operators, CASE expressions). Date math, partial unique indexes, and other dialect-isms move to the helper layer (the concrete `*Store` impl) where engine-specific code is allowed and expected.
4. **Never bypass the engine factory.** Code wanting a connection asks `make_engines(data_dir)` (or constructs an in-memory engine via `open_in_memory_engine` for tests). No `create_engine("sqlite:///...")` calls outside `engines.py`.
5. **Storage methods must declare concrete return types.** The route-layer `cast()` calls disappear. This was the original M9.0 typing-pass deliverable; it stays a standing rule.

**Routes interact with storage only through ABC-typed dependencies.** A clearance handler injects `ClearanceStore`, not `SQLiteClearanceStore`. The dependency wiring (FastAPI `Depends(...)`) lives in `eyenet/api/v1/deps.py` and is the only file that knows the concrete impl class — and even it learns the class via `make_storage()` factory dispatch, not via direct import.

**Tests** use `open_in_memory_engine()` from `eyenet/storage/engines.py` for SQLite in-memory unit tests. Integration tests against a real backend pin `EYENET_STORAGE_TYPE` via fixture.

**Why this matters for the API author:** if the storage layer ever needs to swap to MySQL for an operator deploy, you SHOULD NOT need to touch `eyenet/api/v1/`. The whole point of the abstract factory is that the API layer's contract is "I need a `ClearanceStore`," and the deployment-time wiring decides whether that comes from SQLite or MySQL. Writing a handler that depends on a `SQLite*` type breaks that promise.

### 9.5 Domain model ↔ API schema correlation

Two layers, **never conflated**:

1. **Domain models** live in `eyenet/models/` and are the storage layer's truth. They are versioned by `MODELS.md`. They contain everything: internal flags, denormalized scratch fields, primitive_version stamps, raw bytes. They are not API-shaped.
2. **API schemas** live in `eyenet/api/v1/schemas/` and are **projections** of domain models, scoped to v1's surface. They are Pydantic `BaseModel`s with `ConfigDict(extra="forbid", populate_by_name=True)`. They exist to satisfy OpenAPI, Schemathesis, and codegen — not to be the canonical representation of anything.

The translation is explicit, never `from_orm`-style magic:

```python
# eyenet/api/v1/schemas/linkages.py
from eyenet.models.linkage import Linkage as DomainLinkage

class LinkageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    linkage_id: UUID
    actor_a_id: UUID
    actor_b_id: UUID
    state: LinkageState
    score: float
    proposed_at: datetime

    @classmethod
    def from_domain(cls, m: DomainLinkage) -> "LinkageSummary":
        return cls(
            linkage_id=m.id,
            actor_a_id=m.actor_a_id,
            actor_b_id=m.actor_b_id,
            state=m.state,
            score=m.score,
            proposed_at=m.proposed_at,
        )
```

**Why no `from_orm` / `model_validate`-from-domain magic:**

- When a domain model gains a field, an automatic projector silently picks it up and leaks it. With an explicit `from_domain`, the new field is invisible at the API until a v1 schema PR adds it. The schema author has to decide each release whether the field is operator-relevant.
- Schemathesis tests roundtrip the projection. If a new domain field is `extra="ignore"`-quietly serialized in, Schemathesis's "extra fields aren't in the OpenAPI schema" check fails. Explicit translators eliminate that whole class of drift.
- `MODELS.md` and the API surface map can evolve at different cadences without one breaking the other.

**Correlation discipline (mechanized via the §14.4 contract tests):**

- Every API schema class carries a docstring or attribute pointing at its `MODELS.md` source: `# Projection of MODELS.md §3.2 Linkage`.
- A linter check (custom pytest in `tests/contract/api/`) parses the docstrings and asserts every API schema references a real `MODELS.md` section. Missing reference → fail.
- When a `MODELS.md` section changes, the lint reports which API schemas depend on it (manual review gate, not auto-update).

### 9.6 Response-model matrix

Every endpoint declares an explicit `response_model=` on its FastAPI decorator. No inferred types, no `Any`. The OpenAPI schema then describes the response shape exactly, which is what Schemathesis (§14.5) uses to generate property-based test cases.

| Endpoint | Success status | `response_model` | Notable error responses (in addition to parent's §7) |
|---|---|---|---|
| `POST /v1/auth/login` | 200 | `TokenPair` | 401 wrong creds, 429 throttled |
| `POST /v1/auth/refresh` | 200 | `AccessToken` | 401 refresh revoked/expired |
| `POST /v1/auth/logout` | 204 | `None` | — |
| `GET /v1/auth/me` | 200 | `UserMe` | — |
| `GET /v1/auth/tokens` | 200 | `CursorPage[PATSummary]` | — |
| `POST /v1/auth/tokens` | 201 | `PATMinted` (includes one-time secret) | 409 duplicate name |
| `DELETE /v1/auth/tokens/{token_id}` | 204 | `None` | — |
| `POST /v1/auth/stream-token` | 200 | `StreamTokenMinted` | — |
| `GET /v1/actors/{id}` | 200 | `ActorDetail` | — |
| `GET /v1/actors/{id}/neighbors` | 200 | `NeighborList` (uses §9.3 discriminated union) | — |
| `GET /v1/actors/{id}/observations` | 200 | `CursorPage[ObservationSummary]` | — |
| `GET /v1/actors/{id}/timeline` | 200 | `CursorPage[TimelineEntry]` | — |
| `GET /v1/personas/{id}` | 200 | `PersonaDetail` | — |
| `GET /v1/personas/{id}/members` | 200 | `CursorPage[PersonaMember]` | — |
| `GET /v1/linkages` | 200 | `CursorPage[LinkageSummary]` | — |
| `GET /v1/linkages/{id}` | 200 | `LinkageDetail` | — |
| `GET /v1/graph/stats` | 200 | `GraphStats` | — |
| `GET /v1/graph/search` | 200 | `CursorPage[ActorSummary]` | — |
| `GET /v1/audit` | 200 | `CursorPage[AuditRow]` | — |
| `GET /v1/audit/verify` | 200 | `AuditVerifyResult` | — |
| `POST /v1/linkages/{id}/confirm` | 202 | `WriteAccepted` (subject, event_id, applied, poll) | 409 idempotency conflict |
| `POST /v1/linkages/{id}/reject` | 202 | `WriteAccepted` | 409 |
| `POST /v1/linkages/{id}/suspect` | 202 | `WriteAccepted` | 409 |
| `POST /v1/identities/{id}/claim` | 202 | `WriteAccepted` | 409 |
| `POST /v1/identities/{id}/release` | 202 | `WriteAccepted` | 409 |
| `POST /v1/identities/{id}/freeze` | 202 | `WriteAccepted` | 409 |
| `POST /v1/identities/{id}/burn` | 202 | `WriteAccepted` | 409 |
| `POST /v1/identities/freeze_all` | 202 | `WriteAccepted` | 409 |
| `POST /v1/personas/{id}/merge` | 202 | `WriteAccepted` | 409, 422 (target not a distinct persona) |
| `POST /v1/personas/{id}/split` | 202 | `WriteAccepted` | 409, 422 (actor not a member) |
| `POST /v1/panic` | 202 | `WriteAccepted` | 409 |
| `GET /v1/stream/*` | 200 | SSE — `text/event-stream`, no `response_model` (event shape declared via OpenAPI extensions, see §9.7) | — |
| `GET /v1/metrics` | 200 | Prometheus text — `text/plain; version=0.0.4`, no `response_model` | — |
| `GET /v1/healthz` | 200 | `HealthStatus` | — |
| `GET /v1/readyz` | 200 | `ReadyStatus` | 503 component degraded |

`WriteAccepted` is the shared response shape from §10.3:

```python
class WriteAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str            # bus subject the event will be published on
    event_id: UUID          # the durable audit row's event id
    applied: bool           # always False on first response; clients poll
    poll: str               # URL to GET to see current state
```

`CursorPage[T]` is the generic pagination wrapper from §8:

```python
class CursorPage(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    items: list[T]
    next_cursor: str | None = None
    estimated_total: int | None = None     # only present when ?include_total=1
```

### 9.7 SSE / streaming response declaration

`text/event-stream` is opaque to OpenAPI's response-body machinery. We document the per-event payload shape via OpenAPI extensions on each `/v1/stream/*` operation:

```yaml
x-eyenet-sse-events:
  - subject: attribution.linkage.proposed
    payload_schema: '#/components/schemas/LinkageProposedEvent'
  - subject: attribution.linkage.confirmed
    payload_schema: '#/components/schemas/LinkageStateChangedEvent'
  ...
```

The Pydantic models for the payloads live in `eyenet/api/v1/schemas/stream.py` and are referenced by the codegen pipeline (§12.5) to produce typed TypeScript discriminated unions for the UI's SSE handler. Schemathesis doesn't generate against SSE directly; the per-event payloads are exercised separately by §14.2 integration tests using `httpx.AsyncClient.aiter_lines()`.

---

## 10. Bus integration

The API process is a bus citizen.

### 10.1 On startup (lifespan)

1. Open storage (`engines.open_all`).
2. Load JWT keypair (or generate first-run).
3. Connect to NATS (or `MemoryBus` in tests).
4. Subscribe to `attribution.linkage.*`, `attribution.persona.*`, `eyenet.audit.*`, `eyenet.control.*`, `eyenet.identity.*` via `BusClient.subscribe(subject)` — live-tail only, no durable-consumer semantics required. Replay is served from storage per §6.2 / §6.5, so the bus contract stays the minimal `subscribe(subject) -> AsyncIterator` shape and any backend (MemoryBus, NATS-core, JetStream, future) plugs in unchanged.
5. Start audit publisher (shared client, `BEGIN IMMEDIATE`-style serialization handled at the audit store layer per PLAN §542).
6. Bind socket.
7. Emit `eyenet.audit.service.start` with `service="api"`.

### 10.2 On shutdown

Reverse order. Drain in-flight SSE connections (15s grace, then force-close). Emit `service.stop`. Hash chain stays linear.

### 10.3 Writes flow

The gate is the durable audit append (§5.5), not the bus. The flow:

```
client POST /v1/linkages/{id}/confirm
  → permission check (write:linkage_decision)
  → idempotency check (table lookup)
  → PERSIST eyenet.audit.operator_action to hash chain (BLOCKING — gate)
       on failure → 503; nothing else happens
  → PERSIST domain event row (e.g. linkage state transition) to durable storage
       (where required for replay — see §11.5)
  → publish eyenet.audit.operator_action on bus  (async, retry-on-failure)
  → publish attribution.linkage.confirmed on bus (async, retry-on-failure)
  → record idempotency row {key → response, bus_state: pending|delivered}
  → 202 Accepted
     { "subject": "attribution.linkage.confirmed",
       "event_id": "01HABC...",
       "applied": false,
       "poll": "/v1/linkages/{id}" }
```

The Graph service applies it asynchronously when it receives the bus event. Client polls or watches `/v1/stream/linkages` to see `applied: true`. If the bus is degraded, the retry walker (§5.5) catches up on reconnect; the operator's decision is never lost because step 1 was durable.

Idempotency replay: a repeat of the same `Idempotency-Key` returns the originally stored response unchanged, including its `applied: false`. The client is responsible for checking current state via the poll URL, not for inferring it from the idempotent response body.

---

## 11. Observability & distributed tracing

### 11.0 Layers, by audience

Observability has three layers in EYENET. They answer different questions for different audiences; none replaces the others.

| Layer | Question it answers | Audience | Default |
|---|---|---|---|
| **Audit chain** | "What happened with this evidence? Who touched it, when, why?" | Operator (forensic) | Always on. Differentiator. Section §5. |
| **Metrics** (`/metrics` + OTLP) | "Is the system healthy? Is throughput where it should be? Are we close to a limit?" | Ops / SRE / procurement | Opt-in. §11.7. |
| **Traces** (OTLP) | "Why is this specific request slow / broken? What was the full causal path?" | Developer / SRE / enterprise observability integration | Opt-in. §11.4–§11.6, §11.9. |

The audit chain is the operator's authoritative observability surface. Metrics and traces are *operational* and *diagnostic* respectively — required for enterprise deployments and for any ops team larger than zero people, but never the source of forensic truth.

Tracing is not a feature of the API. It is a feature of the entire EYENET pipeline. The API just happens to be the last hop before bytes arrive at the operator's eyeballs, so the trace either reaches that far or it doesn't reach at all. This section specifies both the system-wide model and the API-local responsibilities within it.

### 11.1 Lineage model

A trace begins at the **Collector**, when an observation is first ingested from a source. It continues — same `trace_id`, parent-child span relationships — through every downstream step that is causally part of processing that observation:

```
Collector observe → Engine recipes → Sensor primitives → Linker propose
   → Verifier suspect/reject → Graph upsert/merge → Audit append
   → (eventually) API SSE delivery to a UI client
```

The trace ends when the last side-effect completes, which for events that the operator subscribes to via SSE is **the byte landing in the UI**.

Independent of that, **a UI-initiated REST request starts its own trace**. The API server span continues the UI's trace. For an evidence dereference (e.g. `GET /v1/actors/{id}`), this UI-trace fans out into storage spans and an `evidence_access` audit-emission span — all rooted at the UI.

So two trace families coexist:

| Family | Root | Carries |
|---|---|---|
| **Event lineage** | Collector observe span | Bus envelopes via `traceparent` |
| **Operator request** | UI client request | HTTP `traceparent` header |

They meet at the API. How they meet at SSE delivery is the crucial detail (§11.4).

### 11.2 Bus envelope — mandatory `traceparent`

Every bus message envelope carries:

```json
{
  "type": "attribution.linkage.proposed",
  "id": "<uuid7>",
  "ts": "...",
  "trace": {
    "traceparent": "00-<32-hex-trace-id>-<16-hex-span-id>-<flags>",
    "tracestate": "<optional vendor-specific>"
  },
  ...payload...
}
```

Producers stamp `trace` from the currently-active span on emit. Consumers extract it on receive and create a child span using the W3C trace context propagator. Missing `trace` field on incoming messages is tolerated (consumer starts a fresh trace and logs a `eyenet.telemetry.trace_propagation_missing` metric increment), so the rollout is backwards-compatible.

**Rollout (NOT big-bang):**

| Milestone | Posture |
|---|---|
| M9.0 | `trace` field added to envelope schema; **tolerated-missing on receive**; producers update opportunistically (API and any service whose code is already touched). `trace_propagation_missing_total` counter exposed but not alerting. |
| M9.1–M9.3 | Each producer service updates in its own commit series to stamp `trace`. No flag day. Counter trends toward zero. Coordinate with `MODELS.md` envelope-version bump in a single PR per producer. |
| M9.6 | `trace` is **REQUIRED** on receive. Missing field on a non-test envelope is a hard error; the counter becomes an alerting SLI. |

This staggered rollout means M9.0 ships safely without forcing every sister service to ship a trace update in lockstep. The hard cutover is deferred until everything is already stamping.

### 11.3 Audit ↔ trace cross-link

Every `eyenet.audit.*` row gains two columns:

| Column | Source |
|---|---|
| `trace_id` | 32-hex, from the active span at audit emission time |
| `span_id` | 16-hex, the span that emitted the audit row |

And every span emitted by EYENET services carries the symmetric attributes when relevant:

| Attribute | When set |
|---|---|
| `eyenet.audit.row_id` | When this span produced an audit row |
| `eyenet.subject` | Bus-event-handling spans — the subject consumed/published |
| `eyenet.user_id` | API request spans, write spans, SSE spans |
| `eyenet.request_id` | API request spans |
| `eyenet.linkage_id` / `eyenet.actor_id` / `eyenet.persona_id` | Domain spans |

Net result: from any audit row you can pivot to the full trace; from any span you can find the audit row it produced (if any).

### 11.4 API-local tracing — REST

- ASGI middleware reads `traceparent` from request headers. If present, continues the UI's trace. If absent, starts a new trace (client is uninstrumented; logged as `trace_propagation_missing` metric).
- One server span per request, named `api.<METHOD>.<route_template>` (e.g. `api.GET./v1/actors/{actor_id}`).
- Standard HTTP attrs: `http.method`, `http.route`, `http.status_code`, `http.response.size_bytes`.
- EYENET attrs: `eyenet.user_id`, `eyenet.request_id`, `eyenet.idempotency_key` (if present), `eyenet.scope_required`.
- Storage and bus operations within the request emit child spans (instrumented via the existing `eyenet/telemetry/` infrastructure — not API-specific).
- Writes that publish to the bus inject the active span's traceparent into the outbound envelope (§11.2). This is how operator actions seed event-lineage traces that downstream consumers continue.

### 11.4.1 API-local tracing — SSE (the tricky one)

Standard FastAPI instrumentation (`opentelemetry-instrumentation-fastapi`) has a known bug where the request span ends on first response byte. For a streaming response this is catastrophic: the span closes within milliseconds, and every delivered event happens "outside" any span. **We disable the stock SSE instrumentation and use a custom middleware.**

The model:

1. **Connection acceptance span** — short-lived span named `api.sse.accept.<stream_name>`, opened at request-accept and closed once the connection is fully established (auth resolved, replay source seeked, first bytes flushed). Belongs to the UI's trace (continues `traceparent` from the request). Attributes: `eyenet.user_id`, `eyenet.stream`, `eyenet.last_event_id`, `eyenet.connection_id`.

2. **Connection segment spans** — the connection's lifetime is sliced into bounded segments of `EYENET_SSE_SEGMENT_SECONDS` (default 60s). Each segment is its own span `api.sse.segment.<stream_name>`, parent = the previous segment span (linked via a per-connection root that lives in the connection acceptance trace, so the segment chain is navigable). Each segment closes cleanly with `events_delivered`, `events_dropped`, `bytes_out` attributes — observability backends now have well-bounded spans instead of multi-hour ones.

   This satisfies the "no span longer than a minute" rule that Jaeger, Tempo, and basically every backend implicitly assume.

3. **Per-event delivery span** — one per event sent to the client. Named `api.sse.delivery`.
   - **Parent:** the event's own trace (extracted from the bus message's `traceparent`). NOT the connection span.
   - **Links:** (a) the current connection segment span, (b) the connection acceptance span. So you can navigate "what connection delivered this event" and "what segment" without losing the upstream lineage.
   - **Attributes:** `eyenet.subject`, `eyenet.event_id`, `eyenet.user_id`, `eyenet.connection_id`, `eyenet.delivery_lag_ms` (now − event ts).

4. **Connection close span** — short span named `api.sse.close.<stream_name>` emitted on disconnect, parented to the connection acceptance span. Attributes: `eyenet.close_reason` (`client_disconnect` | `token_expired` | `scopes_revoked` | `audit_backpressure` | `shutdown`), `total_events`, `total_bytes`, `connection_duration_ms`.

5. **Replay phase** — when the connection opens with `Last-Event-ID`, each replayed event from `StreamReplaySource` (§6.5) gets the same per-event delivery span shape. The event's original trace context is reconstructed from storage (the source carries `traceparent` in its persisted row — see §11.5 below).

This is the model that makes "show me everything that touched this linkage" actually work: the UI delivery span sits at the bottom of the same trace tree that started at the Collector's observe span. And no span outlives a minute, so the trace store cooperates.

### 11.5 Storage — persist traceparent on durable rows

`StreamReplaySource` (§6.5) replays from storage. For the per-event delivery span on replay to be parented correctly, the storage rows must carry the `traceparent` of the event that produced them.

The linkage lifecycle has more than two state transitions (`proposed`, `suspected`, `rejected`, `confirmed`, `released`, possibly future verifier-driven states), and each emits a separate bus event with its own trace context. A two-column scheme cannot represent that.

**Use a per-transition table, not denormalized columns:**

```
linkage_event_log:
  linkage_id          uuid     not null
  event_seq           integer  not null   -- monotonic per linkage_id
  event_subject       text     not null   -- e.g. "attribution.linkage.suspected"
  event_id            uuid     not null   -- the bus event uuid7
  ts                  datetime not null
  traceparent         text     not null
  tracestate          text     null
  actor                text     null      -- system_user_id for operator actions, null for engine
  payload_digest      text     null       -- sha256 of compact payload, for forensic cross-check
  primary key (linkage_id, event_seq)
```

`LinkageReplaySource` reads `linkage_event_log` ordered by `(ts, event_seq)`; the SSE event id is `event_id`; the per-event delivery span (§11.4.1) parents from `traceparent`.

Symmetric tables for any other stream with multi-transition history (e.g. `persona_event_log`, `identity_event_log`). The audit chain already serves this role for `eyenet.audit.*`, so no separate event log there.

This is the storage-side dual of the bus-envelope change in §11.2.

### 11.6 Sampling

Aligns with the existing PLAN.md policy (keep all traces where `attribution.linkage.proposed` is emitted or any span errored; sample the rest). Tail-based sampling at the OTel collector — head-based can't know "this trace will later emit linkage.proposed."

API-specific overrides on top of the global policy:

- **Always sample:** `write:panic` requests, auth failures (`login.failure`, refresh denials), audit-publish failures, any 5xx, any request that emits 503 due to audit unavailability.
- **Always sample stream-control events:** SSE connect/disconnect, `stream.gap`, `stream.backpressure`.
- **Default-sample:** read endpoints at 10%, write endpoints at 100% (they are operator decisions; cheap to keep them all).

### 11.7 Metrics

OpenTelemetry metrics with **dual exposition**: OTLP push for enterprise observability stacks, and a `/v1/metrics` Prometheus scrape endpoint for the much larger pool of operators running plain Prometheus + Grafana. One metric definition feeds both via OTel views.

#### 11.7.1 Exposition surfaces

| Surface | Wire format | Default | Auth | Toggle |
|---|---|---|---|---|
| OTLP push | OTLP/gRPC | off (unset endpoint) | endpoint trust | `EYENET_OTEL_ENDPOINT` |
| `/v1/metrics` scrape | Prometheus text exposition | **off** | scope `read:metrics` | `EYENET_API_METRICS_ENABLED=1` |

Opt-in by environment variable for both. Even when enabled, `/v1/metrics` is scope-gated — there is no anonymous metrics endpoint. Operators using Prometheus run it under a service-account `SystemUser` holding a PAT with `read:metrics` (and nothing else) and configure their scrape job's `authorization` header to that PAT.

Rationale for opt-in default: aligns with §11.9's existing "unset endpoint = traces disabled" posture and avoids leaking label-cardinality reconnaissance from any deployment whose operator hasn't deliberately turned monitoring on. Operators who want metrics flip one env var; the procurement-checkbox conversation is satisfied by "yes, we expose Prometheus, set `EYENET_API_METRICS_ENABLED=1` and point your scrape at `/v1/metrics`."

#### 11.7.2 Metric catalog

API metrics. Cardinality kept bounded by using route templates not raw paths.

```
eyenet_api_requests_total{method, route, status}
eyenet_api_request_duration_seconds{method, route}                histogram
eyenet_api_sse_connections{stream}                                gauge
eyenet_api_sse_events_delivered_total{stream}                     counter
eyenet_api_sse_events_dropped_total{stream, topic, reason}        counter
eyenet_api_sse_terminated_total{stream, reason}                   counter
eyenet_api_sse_delivery_lag_seconds{stream}                       histogram
eyenet_api_auth_events_total{event, outcome}                      counter
eyenet_api_scope_cache_hits_total / _misses_total                 counter
eyenet_api_audit_publish_failures_total                           counter (alert on > 0)
eyenet_api_idempotency_replays_total                              counter
eyenet_api_trace_propagation_missing_total                        counter
```

Health gauges (mirror `/healthz` and `/readyz` for Prom-native alerting; ops teams can skip a separate Blackbox-exporter probe):

```
eyenet_api_healthy                                                gauge (0/1)
eyenet_api_ready{component="storage"|"bus"|"jwt_keys"}            gauge (0/1)
eyenet_api_storage_open                                           gauge (0/1)
eyenet_api_bus_connected                                          gauge (0/1)
```

#### 11.7.3 Cardinality discipline

Labels with unbounded cardinality (per-user, per-target_id, per-event_id, per-request_id) **never** appear in the Prometheus exposition. They would melt any non-trivial deployment's Prom storage within weeks.

Concretely:

- The `eyenet_api_*` metrics defined above have **no `user` label** as exposed via Prometheus. Per-user analytics live in OTLP.
- An OTel **view filter** on the Prometheus exporter strips `eyenet.user_id` and `eyenet.request_id` resource/instrument attributes before exposition. The same metric on the OTLP push keeps them; enterprise backends do their own aggregation.
- Audit-events metric uses `event` (login.success/failure/refresh/logout/…) and `outcome` (success/failure), both bounded enumerations. No `user`.
- New metrics added later must either pass the cardinality check (bounded label set) or be marked `otlp_only` in the metric definition and excluded from the Prometheus exporter by the view.

This rule is non-negotiable. If a customer asks for per-user latency in Grafana, the answer is "run an OTLP collector and aggregate however you like" — not "we'll add a user label." Saying yes to that request once turns the API into a cardinality bomb.

### 11.8 Logging

- Structured JSON via `structlog` or stdlib `logging` with a JSON formatter.
- Every log record carries (when available): `trace_id`, `span_id`, `request_id`, `user_id`, `subject`, `route`.
- Logs, audit rows, and traces share the `trace_id` key — operator can grep any of the three and pivot.

### 11.9 OTel SDK + exporter

- `opentelemetry-sdk` + `opentelemetry-exporter-otlp` (gRPC) for OTLP push of traces and metrics.
- `opentelemetry-exporter-prometheus` for the `/v1/metrics` scrape endpoint (§11.7.1). Both exporters share the same MeterProvider; metrics are defined once.
- Endpoint configurable via `EYENET_OTEL_ENDPOINT` (e.g. `http://localhost:4317`). Unset → traces disabled, OTLP metrics disabled. Prometheus exposition is independently gated by `EYENET_API_METRICS_ENABLED=1`.
- No vendor lock-in: any OTLP-compatible backend (Jaeger, Tempo, Honeycomb, Datadog, SigNoz) works; Prometheus + Grafana works without OTLP at all.
- Resource attributes set at process boot: `service.name=eyenet-api`, `service.version=<git-sha>`, `service.instance.id=<hostname-pid>`, `deployment.environment=<env>`.

### 11.10 Milestones — where tracing lands

Tracing is interleaved with the API milestones, not a separate one:

- **M9.0** — bus envelope `trace` field added in **tolerated-missing** mode (consumers accept absence, log a metric); OTel SDK wired into `eyenet/api/` boot; REST request span middleware; `/healthz` and `/readyz` produce spans; contract-test snapshot for the trace field. No lockstep update of other services required.
- **M9.1** — auth spans (`api.auth.login`, `api.auth.refresh`, `api.auth.logout`), auth event audit rows stamped with `trace_id`/`span_id`.
- **M9.3** — read endpoints emit spans; `evidence_access` audit rows stamped; OTel resource attributes verified end-to-end against a local Jaeger.
- **M9.4** — write endpoints inject outbound `traceparent` into bus envelopes; `operator_action` audit rows stamped; per-transition `*_event_log` tables (§11.5) persist `traceparent` for every state transition (proposed/suspected/rejected/confirmed/etc).
- **M9.5** — custom SSE middleware (the §11.4.1 connection-span + per-event-delivery-span model); replay spans reconstructed from stored `traceparent`; `delivery_lag_seconds` histogram.
- **M9.6** — bus envelope `trace` field flipped to **REQUIRED**; sampling policy tuned; `/v1/metrics` Prometheus exposition wired up alongside OTLP push (§11.7.1) with the cardinality view filters (§11.7.3); alert rules on `eyenet_api_audit_publish_failures_total > 0` and `eyenet_api_trace_propagation_missing_total > 0` shipped as YAML under `operations/alerts/`; example Grafana dashboard checked into `operations/dashboards/`.

---

## 12. Hosting / ops

### 12.1 Process model

- **ASGI server: Hypercorn.** Not uvicorn. uvicorn is HTTP/1.1-only (h11) and we forbid HTTP/1.1 (§12.1.2). Hypercorn speaks HTTP/2 natively via `h2` and HTTP/3 via `aioquic`.
- **Multi-worker is supported and is the production default.** `--workers N` is fine. Each worker is an independent process with its own event loop, its own bus subscriptions, and its own set of accepted SSE connections. SSE connection state is per-connection and per-connection ownership is per-worker by design — no cross-worker visibility required.
- **All cross-worker coherence flows through shared substrate**, never through in-process state:

  | State | Coherence mechanism |
  |---|---|
  | `jwt_denylist` (jti) | Storage table — queried on every auth. |
  | Idempotency records | Storage table `idempotency_record`. |
  | Rate limit buckets | Storage table `rate_limit_bucket` (§12.3). |
  | Scope cache invalidation | `eyenet.auth.scopes_changed` bus subject (§4.4.1). |
  | Stream-token single-use | Storage table `stream_token_consumed`. |
  | Forced SSE termination on revocation | Bus broadcast → each worker walks its own connections. |

- **Worker fan-out for SSE is correct under broadcast bus subjects.** Each worker subscribes independently; bus messages reach every worker; each worker forwards to its own connected clients. Slightly redundant per-worker CPU on subjects no client of that worker subscribes to; acceptable, and lets workers be added/removed without any subscription-group reconciliation.

#### 12.1.1 Process model — protocol stack

- **HTTP/1.1 is forbidden.** ALPN refuses negotiation; clients that don't offer h2 or h3 get a TLS-level handshake failure. Curl users need `--http2`; `httpx` users need `httpx[http2]`. Documented in `/v1/docs`.
- **HTTP/2 is mandatory.** Hypercorn configured with `bind = "host:port"`, `alpn_protocols = ["h2", "h3"]` (or `["h2"]` if H3 disabled), TLS termination either in-process or at upstream proxy (see §12.2).
- **HTTP/3 (QUIC) is an opt-in feature flag.** `EYENET_API_ENABLE_H3=1` enables Hypercorn's `aioquic` listener on the same port via UDP. Default off in M9; promoted to default in a later milestone after the ops story (UDP/443 firewall, reverse-proxy QUIC support, monitoring) is validated.
- **No HTTP/1.1 fallback path exists.** A reverse proxy in front of the API must speak h2 or h3 backwards as well — proxy-to-backend is not an HTTP/1.1 carve-out.

#### 12.1.2 Why forbid HTTP/1.1 outright

- The operator UI needs multiple concurrent SSE streams (`/stream/linkages`, `/stream/personas`, `/stream/audit`) plus REST calls plus asset loads. HTTP/1.1's 6-connection-per-origin browser cap saturates immediately. HTTP/2 multiplexes the lot over one connection.
- One protocol is fewer test matrices, fewer middleware bugs, fewer "works on h1 broken on h2" surprises.
- Every modern HTTP client supports h2. The cost of forbidding h1.1 is "external integrators using legacy tooling read a docs line"; the cost of allowing it is structural.

### 12.2 Bind defaults

| Setting | Default | Override |
|---|---|---|
| host | `127.0.0.1` | `EYENET_API_HOST` |
| port (TCP, h2) | `8765` | `EYENET_API_PORT` |
| port (UDP, h3) | same as TCP port | `EYENET_API_PORT_H3` |
| allow non-loopback bind | `false` | `EYENET_API_ALLOW_PUBLIC=1` (operator opt-in, same as today's gate) |
| enable HTTP/3 (QUIC) | `false` | `EYENET_API_ENABLE_H3=1` |
| enable `/v1/metrics` (Prometheus) | `false` | `EYENET_API_METRICS_ENABLED=1` |
| OTLP endpoint (traces + metrics push) | unset | `EYENET_OTEL_ENDPOINT` |
| workers | `1` | `EYENET_API_WORKERS=N` |

Notes:

- `EYENET_API_ALLOW_PUBLIC=1` ALSO requires `EYENET_API_TRUST_PROXY_HEADERS=1` to be explicit — otherwise the API refuses to start with public bind, because we'd be logging the wrong client IP into the audit chain. Audit IP integrity > convenience.
- When `EYENET_API_ENABLE_H3=1`, the API binds UDP on the same port for QUIC. Operator must ensure UDP/<port> traversal through any firewall or reverse proxy — silent QUIC drops degrade clients to h2, which is correct fallback but worth knowing about.
- Workers > 1 requires TLS termination upstream (no in-process TLS per-worker contention) OR Hypercorn launched via its multi-worker arbiter — either model is fine, configurable in the `eyenet api` CLI launcher.

### 12.3 Rate limiting

Per-token sliding window. Defaults:

| Surface | Limit |
|---|---|
| `/v1/auth/login` | 5 / minute / IP |
| writes | 60 / minute / user |
| reads | 600 / minute / user |
| `/v1/stream/*` | 4 concurrent connections / user |

Storage-backed (SQLite table `rate_limit_bucket`). 429 with `Retry-After`.

> **Implemented (M9.I1, `eyenet/api/middleware/rate_limit.py`) — partial.** A
> pure-ASGI sliding-window limiter meets the DoD (429 + `Retry-After` +
> `X-RateLimit-Remaining`; `time.monotonic` so clock skew can't shift the
> window). Simplifications vs the spec above, deferred until a real operator
> needs them:
> - **Single global limit**, not the per-surface table — env `EYENET_API_RATE_LIMIT`
>   (default 300) / `EYENET_API_RATE_WINDOW_SECONDS` (default 60), `=0` disables.
> - **In-memory per-process**, not the `rate_limit_bucket` SQLite table — fine at
>   the small-operator default cardinality 1; horizontal scale needs a shared
>   store (Redis). Keyed per credential (`sha256(bearer)[:16]`) or client IP.
> The per-surface floors and storage backing are the upgrade path, not shipped.

### 12.4 CORS

For the operator UI's origin only. Configurable list. No `*`. `Access-Control-Allow-Credentials: true`. `Access-Control-Expose-Headers: X-Request-Id, X-RateLimit-Remaining`.

> **Implemented (M9.I2, `eyenet/api/middleware/cors.py` + `create_app`).** Origins
> come from env `EYENET_API_CORS_ORIGINS` (comma-separated), **not `config.toml`**
> — this codebase has no config.toml loader; every API knob is `EYENET_API_*`.
> Empty default → the CORS middleware is not added at all (never `*`). The
> `X-Forwarded-For` half lives in `eyenet/api/middleware/xff.py`, gated by
> `EYENET_API_TRUST_PROXY_HEADERS`.

### 12.5 OpenAPI

`/v1/openapi.json` and `/v1/docs`. Both require `read:graph` (any authenticated user gets them); no anonymous schema disclosure when `ALLOW_PUBLIC=1`.

> **Implemented (M9.I2, `eyenet/api/v1/meta/api_openapi.py`).** The built-in
> anonymous schema route is disabled (`openapi_url=None` in `create_app`); a
> custom `read:graph`-gated `/v1/openapi.json` serves the schema instead
> (`app.openapi()` still generates it in-process for tests/codegen dumps). The
> gate is **unconditional**, not tied to `ALLOW_PUBLIC` — simpler and always
> safe. `/v1/docs` (Swagger UI) remains OFF (`docs_url=None`); enabling it is a
> deferred nice-to-have.

Codegen target: TypeScript client for the future UI, generated from `/v1/openapi.json` via `openapi-typescript-codegen`. Lives in a sibling repo when the UI starts; the API only owns the spec.

---

## 13. Layout

```
eyenet/api/
  __init__.py
  app.py                 # create_app(deps) with lifespan
  config.py              # APIConfig (pydantic-settings)
  deps.py                # storage, bus, current_user, current_scopes
  errors.py              # problem+json exception handlers
  middleware/
    audit.py             # evidence_access emission
    request_id.py        # X-Request-Id in/out
    rate_limit.py
    proxy.py             # X-Forwarded-For handling (gated by TRUST_PROXY_HEADERS)
  metrics/
    __init__.py
    instruments.py       # OTel Meter, metric definitions (the §11.7.2 catalog)
    prometheus.py        # PrometheusExporter + cardinality view filters (§11.7.3)
    route.py             # GET /v1/metrics handler (scope-gated read:metrics)
  auth/
    __init__.py
    jwt.py               # RS256 sign/verify, kid rotation
    passwords.py         # argon2id
    pats.py
    permissions.py       # RequireScope dependency factory
    storage.py           # SystemUserCredentialStore, RefreshTokenStore, PATStore
  v1/
    __init__.py                            # the surface map: imports every api_*.py router and
                                           # assembles `v1_router: APIRouter` with shared `responses={...}`
    schemas/                               # (see §9.1)

    auth/
      __init__.py
      api_login.py
      api_refresh.py
      api_logout.py
      api_get_me.py
      api_list_tokens.py
      api_mint_token.py
      api_revoke_token.py
      api_stream_token.py                  # POST /v1/auth/stream-token (§6.4.2)
      _passwords.py                        # argon2id helpers
      _denylist.py                         # jwt_denylist lookup

    actors/
      __init__.py
      api_get_actor.py
      api_get_neighbors.py
      api_list_observations.py
      api_get_timeline.py
      _serializers.py

    personas/
      __init__.py
      api_get_persona.py
      api_list_members.py

    linkages/
      __init__.py
      api_list_linkages.py
      api_get_linkage.py
      api_confirm_linkage.py
      api_reject_linkage.py
      api_suspect_linkage.py
      _guards.py                           # state-transition guards

    graph/
      __init__.py
      api_get_stats.py
      api_search.py

    audit/
      __init__.py
      api_list_audit.py
      api_verify_audit.py
      _query.py

    identities/
      __init__.py
      api_claim_identity.py
      api_release_identity.py
      api_freeze_all.py

    panic/
      __init__.py
      api_panic.py

    stream/
      __init__.py
      api_stream_linkages.py
      api_stream_personas.py
      api_stream_audit.py
      api_stream_control.py
      api_stream_all.py
      _sources.py                          # StreamReplaySource implementations (§6.5)
      _backpressure.py                     # per-topic queue (§6.3)
      _sse.py                              # SSE wire format + heartbeat
      _connection_span.py                  # segment-span helpers (§11.4.1)

    health/
      __init__.py
      api_healthz.py
      api_readyz.py

    metrics/
      __init__.py
      api_metrics.py                       # GET /v1/metrics (scope-gated read:metrics)
      _instruments.py                      # OTel Meter + §11.7.2 catalog
      _prometheus.py                       # PrometheusExporter + cardinality view filters (§11.7.3)

# File-naming convention:
#   api_<verb>_<noun>.py     — exactly one HTTP endpoint per file; exports `router: APIRouter`
#   _<name>.py               — module-private helpers
#   __init__.py (per resource) — empty or near-empty; does NOT re-export
#
# Locator function: a bug report citing /v1/linkages/{id}/confirm maps directly to
# eyenet/api/v1/linkages/api_confirm_linkage.py. No grep needed.
#
# Registration pattern: `eyenet/api/v1/__init__.py` is the canonical, explicit surface map.
#   - Top of file: `from .auth.api_login import router as login_router` for every endpoint.
#   - Body of file: `v1_router.include_router(login_router)` grouped by section comment.
#   - Common error envelopes declared once on the parent APIRouter via `responses={...}`
#     pointing at `ProblemDetail` (§7) — typed, not description-only:
#
#         from .schemas.errors import ProblemDetail
#         v1_router = APIRouter(
#             prefix="/v1",
#             responses={
#                 400: {"model": ProblemDetail, "description": "Malformed request"},
#                 401: {"model": ProblemDetail, "description": "Missing/invalid credentials"},
#                 403: {"model": ProblemDetail, "description": "Insufficient scope"},
#                 404: {"model": ProblemDetail, "description": "Resource not found"},
#                 422: {"model": ProblemDetail, "description": "Validation failure"},
#                 429: {"model": ProblemDetail, "description": "Rate limited"},
#                 503: {"model": ProblemDetail, "description": "Audit/storage/bus down"},
#             },
#         )
#
#     These propagate into every child for OpenAPI codegen, Schemathesis, and TS client types.
#   - Adding an endpoint REQUIRES two new lines in `v1/__init__.py` — visible in every PR.
#   - `eyenet/api/app.py` imports `from eyenet.api.v1 import v1_router` and mounts it once.
#
# No auto-discovery, no reflection. Explicit > implicit. ImportError at boot beats silent
# endpoint dropout in production.

tests/unit/api/                              # per-handler unit tests via TestClient
tests/integration/api/                       # full app + real storage + MemoryBus
tests/e2e/api/                               # Hypercorn + real NATS (EYENET_E2E=1)
tests/contract/api/                          # OpenAPI snapshot, route surface, metric cardinality
  schemathesis/
    auth/test_schemathesis_login.py          # one file per endpoint, mirrors eyenet/api/v1/<resource>/api_*.py
    auth/test_schemathesis_refresh.py
    ...
    linkages/test_schemathesis_confirm_linkage.py
    ...
    stateful/test_schemathesis_audit_chain_invariant.py   # cross-endpoint suite (§14.5.4)

# Test-locator function (symmetric to the §13 handler-locator function):
#   eyenet/api/v1/linkages/api_confirm_linkage.py
#   tests/contract/api/schemathesis/linkages/test_schemathesis_confirm_linkage.py
# Editing one and running the other is a 1:1 mapping. Surface-map contract test (§14.4)
# enforces the bidirectional invariant — neither side can drift.
```

`eyenet/query_api/` stays in place until M9.3 ships read parity, then deleted in one commit with all imports redirected.

---

## 14. Test strategy

Mirrors `TESTING.md`. Four tiers:

### 14.1 Unit (`tests/unit/api/`)
- `TestClient` over `create_app(storage=fake, bus=MemoryBus)`.
- One test file per router. Cover: happy path, 404, 401, 403, 422, 409 (idempotency conflict), audit-emission assertion.
- Use `pytest-httpx` for any outbound HTTP if needed.

### 14.2 Integration (`tests/integration/api/`)
- Real `SQLiteStorage` (tmp dir), `MemoryBus`.
- Full request → audit emission → bus subject → storage application chain.
- SSE tests use `httpx.AsyncClient` with `aiter_lines()`.

### 14.3 E2E (`tests/e2e/api/`, `EYENET_E2E=1`)
- Real `nats-server -js` via testcontainers or `EYENET_NATS_URL`.
- Real Hypercorn process speaking h2; httpx (with `http2=True`) talks to it.
- One scenario: login → list linkages → SSE subscribe → confirm via POST → see SSE event arrive → verify audit chain unbroken.

### 14.4 Contract (`tests/contract/api/`)
- Snapshot `GET /v1/openapi.json` to a checked-in fixture.
- CI fails on diff unless the snapshot is intentionally updated.
- Acts as our deprecation guard.
- **Metric cardinality test:** parse the live `/v1/metrics` exposition, assert every metric's label set is a subset of an explicit allow-list checked into the test fixture, and assert NO metric carries `user`, `user_id`, `target_id`, `event_id`, `request_id`, or any unbounded-cardinality label. This is the mechanized form of §11.7.3 — humans will eventually try to add a `user` label "for debugging." This test stops them at PR review.
- **Metric catalog test:** assert every metric named in §11.7.2 is present in the exposition (no silent renames or drops between releases).
- **Route surface test:** asserts that the set of `(method, path)` mounted by `create_app()` is **exactly equal** to the checked-in expected surface map. Missing route → test fails. Extra route → test fails (forces the §3 table to be updated when a new endpoint lands). With explicit registration (§13) this test mostly guards against accidental include-router omissions in `v1/__init__.py` and silent path-prefix drift from a per-handler `APIRouter(prefix=...)`. The expected-surface fixture lives at `tests/contract/api/expected_routes.json`; §3's markdown table is generated from it during doc builds.
- **Handler ↔ Schemathesis-test 1:1 mapping:** for every `eyenet/api/v1/<resource>/api_<verb>_<noun>.py` there must exist a `tests/contract/api/schemathesis/<resource>/test_schemathesis_<verb>_<noun>.py`, and vice versa. The test walks both trees and asserts set-equality. Missing test file when a handler ships → CI fails. Stale test file when a handler is deleted → CI fails. This is what makes "change one route, run one test file" a stable property of the codebase instead of a fragile convention.

### 14.5 Schemathesis (`tests/contract/api/schemathesis/`)

Property-based API testing driven by the live `/v1/openapi.json`. This is the tier that catches "the schema says response X, the handler returns Y" drift — the failure mode §9.5 / §9.6 exist to prevent. Run on every CI build.

#### 14.5.1 File-per-endpoint layout

The test tree **mirrors the §13 handler layout** so the locator function is symmetric: a bug in `api_confirm_linkage.py` is exercised by `test_schemathesis_confirm_linkage.py`, and only that file needs to run during the fix.

```
tests/contract/api/schemathesis/
  __init__.py
  conftest.py                                # shared fixtures: live app, auth headers, openapi schema loader

  auth/
    test_schemathesis_login.py
    test_schemathesis_refresh.py
    test_schemathesis_logout.py
    test_schemathesis_get_me.py
    test_schemathesis_list_tokens.py
    test_schemathesis_mint_token.py
    test_schemathesis_revoke_token.py
    test_schemathesis_stream_token.py

  actors/
    test_schemathesis_get_actor.py
    test_schemathesis_get_neighbors.py
    test_schemathesis_list_observations.py
    test_schemathesis_get_timeline.py

  linkages/
    test_schemathesis_list_linkages.py
    test_schemathesis_get_linkage.py
    test_schemathesis_confirm_linkage.py
    test_schemathesis_reject_linkage.py
    test_schemathesis_suspect_linkage.py

  # ... mirror every api_*.py under eyenet/api/v1/

  stateful/
    test_schemathesis_audit_chain_invariant.py   # the cross-endpoint stateful suite (§14.5.4)
```

**Naming rule:** `test_schemathesis_<verb>_<noun>.py`. One file per endpoint, exactly matching the handler's `api_<verb>_<noun>.py` minus the `api_` prefix. The route surface contract test (§14.4) is extended to also assert the handler ↔ schemathesis-test 1:1 mapping: every `api_*.py` has a matching `test_schemathesis_*.py` and vice versa. Missing test → CI fail, including on M9.0 stubs.

#### 14.5.2 Pytest markers

Every Schemathesis test file is marked `@pytest.mark.contract`. The `contract` marker is declared in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "contract: API contract tests (Schemathesis, OpenAPI snapshot, surface map, metrics cardinality)",
    "integration: full app + real storage + MemoryBus",
    "e2e: real Hypercorn + real NATS (requires EYENET_E2E=1)",
    "load: load tests (k6, manual)",
]
```

Local developer workflow:

```bash
# Just changed api_confirm_linkage.py — run only its contract test:
pytest tests/contract/api/schemathesis/linkages/test_schemathesis_confirm_linkage.py

# Run the whole contract tier (CI gate):
pytest -m contract

# Skip contract tier entirely during a fast inner-loop change:
pytest -m "not contract"
```

CI runs `pytest -m contract` as its own job, parallelized across files via `pytest-xdist`. A change to one endpoint runs one file (~seconds); a change to `routes`, parent-router responses, or the OpenAPI snapshot runs the whole tier.

#### 14.5.3 Generator + auth setup

- **Generator config:** Hypothesis-based, seed pinned in CI, max 100 examples per operation. Local devs can crank to 1000+ for deeper exploration via `EYENET_SCHEMATHESIS_EXAMPLES=1000`.
- **Coverage:** every endpoint in §9.6 except SSE (`text/event-stream` and Prometheus exposition are not Schemathesis territory; they have their own tests in §14.2).
- **Auth fixture (in `conftest.py`):** mints a JWT with every scope plus one PAT, exposes both as fixtures; per-test files pick the right one via OpenAPI security definitions. Auth setup is centralized once — each per-endpoint file is a thin "load the schema, target one operation, run the property check" wrapper.
- **What each per-endpoint file catches:**
  - Response body does not validate against declared `response_model` (extra fields, missing required, wrong types).
  - Error responses don't validate against `ProblemDetail`.
  - 5xx from any input that the schema considers valid (always a bug — must be 422 or a typed 4xx instead).
  - Path/query parameter parsing accepts inputs the schema forbids, or rejects inputs the schema permits.

#### 14.5.4 Stateful mode

The cross-endpoint stateful suite lives under `tests/contract/api/schemathesis/stateful/` and is **not** subject to the file-per-endpoint rule — it exercises operation graphs that span endpoints by definition. Schemathesis builds graphs like (login → mint PAT → confirm linkage → list audit → verify) and asserts invariants across multi-step runs. The audit chain `verify` endpoint at the end of every stateful run MUST return clean — that single assertion catches a huge class of subtle write-path bugs.

The stateful suite is the slow one; it runs in CI but local devs invoke it explicitly:

```bash
pytest tests/contract/api/schemathesis/stateful/ -m contract
```

It also catches the `Idempotency-Key` replay-returns-different-body class of bugs that single-endpoint files cannot.

#### 14.5.5 Failure handling

Any Schemathesis finding is a hard CI fail. No "known flakies" allowlist — if Schemathesis is wrong, fix the schema; if the handler is wrong, fix the handler; if the test is flaky, find the nondeterminism. Hypothesis seeds are pinned in CI so failures are deterministically reproducible from the test output alone.

### 14.6 Load (`tests/load/api/`, optional)
- k6 scripts: read-heavy mix (1000 RPS), SSE fan-out (500 concurrent subscribers).
- Not gating; run locally before each release.

Coverage gate: the current floor inherited from M8 is **0.845** (calibration-suite carve-out). M9.0–M9.5 hold this floor. M9.6 raises it to **0.89**, the original pre-M8 target. No interim hops; pick the number once and ship to it.

---

## 15. Open questions

1. **Password reset flow.** SystemUser doesn't have email today. Resets via CLI (`eyenet user reset-password <name>`)? Out-of-band reset link? Provisional answer: CLI-only for v1, no self-service reset.
2. ~~**Audit publish failure semantics.**~~ **RESOLVED** in §5.5: storage append is the gate; bus publish is async fan-out with a retry walker over rows whose `bus_published_at IS NULL`. Storage health determines request success; bus health determines SSE freshness.
3. **Bulk-read audit cost.** `/v1/actors/{id}/observations?limit=500` emits 500 audit rows. That's the contract — operator-grade evidence is the whole point, and bulk-export inherits the same row-per-evidence cost. **Implementation:** the audit append for a bulk read is a **single `BEGIN IMMEDIATE` transaction containing all N rows**, not N separate transactions. The hash chain links each row to its predecessor inside the txn; commit is atomic. P99 stays in the tens-of-ms range instead of seconds because we pay one fsync per request, not N. The audit-store API gains a `append_many(rows: list[AuditRow]) -> list[AuditRowId]` method to express this; route handlers MUST use it for bulk endpoints.
4. **WebSocket later?** Holding the line on SSE for v1. Revisit when a real use case appears.
5. **`MODELS.md` §2.17 SystemUser scope storage.** Is scope-per-user already modeled, or do we add it here? Action: confirm before M9.1 starts; if missing, add as a MODELS amendment in the same PR.
6. **Idempotency key TTL.** ~~24h? 7d?~~ **RESOLVED 2026-09-21: 7d.** Storage
   cost is low; longer retention is more forensically defensible (operator-grade
   evidence posture). The M9.G1 middleware enforces a 7-day window.
7. **JWT key rotation cadence.** Manual via `eyenet api rotate-keys` CLI for v1. Automated rotation deferred.
8. **Scope cache TTL.** §4.4.1 sets 60s. Revisit after first load test: if scope lookup is genuinely free on indexed SQLite reads, drop to 0 (no cache) and remove the carve-out list. Caching exists only to make the design defensible under load; if there's no load problem, it's surface area we don't need.
9. **PAT scope semantics.** PATs today inherit live `system_user_scope` like JWTs do. Alternative: PATs carry a frozen scope subset at mint time (typical OAuth2 PAT pattern), so revoking a user's scope doesn't silently broaden every PAT's effective grant inversely. Provisional: live lookup (matches JWT path), but worth a second think before M9.2.

---

## 16. Milestones

**Sizing rule.** Every remaining milestone is sized to land in a single worktree (`.claude/worktrees/<slug>`), one commit series, one `--no-ff` merge to main. Target: half-day to two-day execution window per slice. If a milestone needs more than two days, split it again.

**Independence rule.** Milestones declare an explicit `Depends on:` line listing the *minimum* prior merges they need. Anything not listed is parallel-safe. Two milestones with disjoint `Files touched:` sets can be executed concurrently in two worktrees by two operators (or two Claude sessions) without merge pain — the pre-public posture (no Alembic, `rm data/*.db && eyenet init`) means even FK-sharing storage milestones don't serialize through migrations.

**Group convention.** Letters are independence groups, not strict ordering:
- **9.0 / 9.1a / 9.1a.5** — historical, shipped, foundation.
- **A — Auth & tokens** (sequential within group, parallel to all other groups)
- **B — File-access journal** (independent of A, C, D, E, F, G, H)
- **C — Discovery storage** (independent of A, B, F, G, H)
- **D — Discovery API surface** (depends on C; parallel to E)
- **E — Discovery runtime** (depends on C; parallel to D)
- **F — Read surface** (depends on 9.1a only; parallel to A, B, C, G, H)
- **G — Write surface** (depends on 9.1a only; parallel to A, B, C, F, H)
- **H — SSE streaming** (depends on G for event logs; parallel to F)
- **I — Hardening** (final; depends on F + G + H)

Each milestone block carries: scope (1–3 bullets), `Depends on:`, `Files touched:` (worktree-collision predictor), `DoD:` (verification gate).

---

### M9.0 — Skeleton
- `eyenet/api/` package + `create_app(...)` with lifespan.
- `APIConfig` (pydantic-settings, env-var driven).
- `problem+json` exception handlers + `request_id` middleware.
- `/v1/healthz` and `/v1/readyz`.
- OpenAPI mounted at `/v1/openapi.json` and `/v1/docs`.
- `eyenet api` CLI command replacing `eyenet graph-api`. Launcher uses Hypercorn (not uvicorn — §12.1) with ALPN `["h2"]` by default; `EYENET_API_ENABLE_H3=1` adds `"h3"`. HTTP/1.1 is never offered.
- **Explicit router registration** in `eyenet/api/v1/__init__.py` per the §13 layout: every endpoint imported by name at the top, included into the parent `v1_router` in section-grouped blocks. Common error envelopes (400/401/403/404/422/429/503) declared once on `v1_router` via `responses={...}` and propagate into every child for OpenAPI codegen. `eyenet/api/app.py` mounts `v1_router` exactly once. No auto-discovery, no reflection — adding an endpoint requires two lines in `v1/__init__.py`, visible in every PR diff.
- **Startup registration audit log:** the `api.startup` span (§11.4) emits a structured `eyenet.api.routes_mounted` event with the full list of `(method, path, handler_module)` tuples at INFO. Duplicate paths or method collisions fail loudly at boot (FastAPI already raises on these; we just surface the failure to the audit/trace stream so it's discoverable from observability alone).
- `eyenet/api/v1/schemas/errors.py` (`ProblemDetail`, `ValidationError`) and `eyenet/api/v1/schemas/health.py` shipped in M9.0 — the parent router's `responses={...}` map references `ProblemDetail` from the first commit. No description-only error declarations.
- Contract test fixture established (see §14.4); the `expected_routes.json` fixture seeded with `/v1/healthz`, `/v1/readyz`.
- **Schemathesis** (§14.5) wired into CI from the M9.0 skeleton onward, even though the surface is two endpoints — running it from the start prevents schema/handler drift from being introduced in any later milestone.
- **No auth yet.** Localhost-only enforced at startup (refuse non-loopback bind).
- **Definition of done:** existing `eyenet/query_api/` integration test ported as an unauth'd smoke test and passing; Schemathesis CI step green.

### M9.1 — Storage build-out (split into 9.1a / 9.1b / 9.1c)

The M9.0 wire surface ships 62 v1 routes, but every handler beyond `/healthz`/`/readyz` raises `NotImplementedError` because the backing tables don't exist. M9.1 is the storage layer that unblocks them. We split it into three focused milestones so each lands as a reviewable commit series, each with its own verification gate. Order is fixed: 9.1a → 9.1b → 9.1c.

Pre-public posture stands: no Alembic, schema changes = `rm data/*.db && eyenet init` (§17 "What we are NOT doing in v1"). Alembic baseline lands at v0.1.0.

#### M9.1a — Evidence-access storage

Unblocks every handler in §4.6–4.8 (clearance), §4.9 (reclassification), and §4.10 (cases) — 19 endpoint stubs from M9.0.

- **New tables in `audit.db`:**
  - `system_user_clearance_grant` (§4.6–4.8) — grant lifecycle with CHECK on 90-day expiry, reason length ≥16, revocation-after-grant ordering. Scopes: `read:restricted`, `read:classified`, `admin:reclassify`, `admin:case`.
  - `case_v2` (§4.10) — replaces the legacy stub `case_` table wholesale; new `__tablename__` makes the break explicit. Materialised `effective_tier` column.
  - `case_member` (§4.10) — m:n junction with partial unique index `(case_id, subject_kind, subject_id) WHERE removed_at IS NULL`. Subject kinds: observation, attachment, message, actor, persona, linkage.
  - `case_collaborator` (§4.10) — m:n with partial unique `(case_id, user_id) WHERE revoked_at IS NULL`. Roles: owner, analyst, reviewer.
- **Columns added to existing tables:**
  - `ObservationTable.classifier_tier` + `.operator_tier_override` (§4.7 / §4.9) — monotonicity CHECK at the storage layer (operator override rank ≥ classifier rank).
  - `AttachmentTable.classifier_tier` + `.operator_tier_override` (same CHECK).
- **Enum additions** to `eyenet/contracts/enums.py`: `SensitivityTier`, `ClearanceScope`, `CaseStatus`, `CaseSubjectKind`, `CaseRoleOnCase`. The five API-side enums lift into shared contracts so storage and API share one StrEnum each.
- **Audit-subject registry** at `eyenet/contracts/audit_subjects.py` (new) — central canonical list of every subject string. Registered: `eyenet.audit.clearance.{granted,revoked,expired}`, `eyenet.audit.reclassify.{observation,attachment,rejected}`, `eyenet.audit.case.{created,updated,member_added,member_removed,collaborator_added,collaborator_revoked,closed,reopened,archived,tier_changed,access_denied}`.
- **Thin storage helpers:** `eyenet/storage/clearance.py`, `eyenet/storage/cases.py`; `reclassify_observation` / `reclassify_attachment` added to existing modules. Each write emits its audit row in the same transaction (cross-engine atomicity is the caller's responsibility, documented).
- **Cache-bypass note (§4.4.1):** `case_member` and `case_collaborator` resolution joins the no-cache list. TODO comment left in code until the M9.1b auth resolver lands.
- **`_STORE_TABLES` update** (`engines.py`): remove legacy `"case_"` from MESSAGES; add the four new tables to AUDIT.
- **Tests** in `tests/unit/storage/`: `test_clearance.py`, `test_cases.py`, `test_reclassify.py` covering CHECK enforcement, partial-unique behaviour, soft-delete round-trip, monotonicity rejection.
- **Definition of done:** new tests pass; existing 914-test suite green; coverage ≥ 0.84; `mypy eyenet/models/ eyenet/storage/` clean; `rm -rf data/*.db && open_all(...)` bootstraps; `sqlite3 data/audit.db ".schema"` shows the four CHECK constraints.

#### M9.1a.5 — Storage abstract-factory cutover (intermediary)

**Shipped 2026-05-24/25, 18 commits, merge `5efbe50`.** Prerequisite for everything in M9.1b/c/2/3/4/5: every later handler is typed against `BaseRepository`, not the legacy sub-stores. This was the deepest non-content refactor in the M9 chain and is documented here so the architecture history is auditable.

**Problem this fixed.** M9.1a shipped four new tables but the storage layer they landed in had drifted into 15 sub-store ABCs (`MessageStore`, `CaseStore`, `ClearanceStore`, `AuditStore`, …) backed by 17 separate `SQLite<Name>Store` files. Most of each impl was generic SQLModel ORM that would run unchanged against Postgres or MySQL. The dialect-specific surface was tiny (the audit `BEGIN IMMEDIATE` raw-cursor write, pragmas, the in-memory engine, a couple of generated-column expressions). Splitting the persistence surface 15 ways meant every new handler in M9.1b–M9.5 would be a 20-file diff. The M9.1a.2b helper work duplicated the very anti-pattern this fixes.

**Target shape (DECNET pattern).**

```
eyenet/storage/
  __init__.py            # exports BaseRepository, get_repository, errors, blob helpers — NO concrete classes
  errors.py              # backend-neutral exceptions
  attachments.py         # blob helpers — attachment_root / store_attachment
  factory.py             # get_repository(**kwargs) → BaseRepository, env-dispatched on EYENET_STORAGE_TYPE
  repository.py          # BaseRepository(ABC) — flat ~80-method async ABC
  sqlmodel_repo/         # generic SQLModel/SQLAlchemy mixin layer (ANSI SQL only)
    __init__.py          #   SQLModelRepository(BaseRepository) — mixin compose + session() escape hatch
    _helpers.py          #   safe_session, build_audit_row, audit_or_warn, TIER_RANK
    audit.py             #   AuditMixin — append_audit / all_audit (BEGIN IMMEDIATE override lives in SQLiteRepository)
    cases.py             #   CasesMixin — create_case, close_case, add_case_member, …
    clearance.py         #   ClearanceMixin — grant_clearance, expire_due_clearances, active_clearance_grants_for, effective_clearance_scopes
    corpus.py            #   CorpusMixin — append_corpus, iter_corpus_since
    cursors.py           #   CursorsMixin — get_cursor, set_cursor, get_cursors_bulk, set_cursors_bulk
    actors.py            #   ActorsMixin — upsert_source/group/actor, resolve_actor_id
    attachments.py       #   AttachmentsMixin — put_attachment, reclassify_attachment
    feedback.py          #   FeedbackMixin — record_feedback_pair, get_feedback_pair, all_feedback_pairs
    graph.py             #   GraphMixin — upsert_graph_node, upsert_graph_edge, graph_neighbors, graph_stats
    linkages.py          #   LinkagesMixin — insert_proposed_linkage, transition_linkage, list_linkages
    messages.py          #   MessagesMixin — put_message, get_message_body, resolve_message_id, recent_message_bodies_for_actor
    observations.py      #   ObservationsMixin — put_observation, put_observations_bulk, reclassify_observation
    personas.py          #   PersonasMixin — merge_actors_into_persona, split_actor_from_persona, persona_for_actor
    profiles.py          #   ProfilesMixin — get_current_profile, upsert_current_profile, profile_history
    syslog.py            #   SyslogMixin — append_syslog
    vectors.py           #   VectorsMixin — upsert_simhash, nearest_simhashes
  sqlite_repo/           # concrete SQLite backend (~200 lines of overrides)
    database.py          #   get_async_engine / get_sync_engine / init_main_db / init_audit_db / init_lock / open_in_memory_*
    repository.py        #   SQLiteRepository(SQLModelRepository) — overrides:
                         #     _append_audit_locked (BEGIN IMMEDIATE on raw aiosqlite cursor, hash-chained)
                         #     set_cursors_bulk     (INSERT … ON CONFLICT DO UPDATE — race-safe)
                         #     __init__             (engine wiring + init lock)
```

Future MySQL/Postgres backends slot in as `eyenet/storage/mysql_repo/repository.py` and `eyenet/storage/postgres_repo/repository.py` with their own ~5-method override sets (`information_schema`, `INSERT IGNORE`, `SERIALIZABLE`, `ON CONFLICT`). They share the entire `sqlmodel_repo/` mixin layer.

**Naming map (every flat method = `<verb>_<domain>`).** Every caller uses dotless access — no more `storage.cases.create_case(...)`; instead `await storage.create_case(...)`.

| Old (sub-store)                              | New (flat)                                  |
|----------------------------------------------|---------------------------------------------|
| `storage.audit.append(...)`                  | `await storage.append_audit(...)`           |
| `storage.cases.create_case(...)`             | `await storage.create_case(...)`            |
| `storage.cases.add_member(...)`              | `await storage.add_case_member(...)`        |
| `storage.clearance.grant(...)`               | `await storage.grant_clearance(...)`        |
| `storage.clearance.expire_due(...)`          | `await storage.expire_due_clearances(...)`  |
| `storage.observations.put(...)`              | `await storage.put_observation(...)`        |
| `storage.observations.reclassify(...)`       | `await storage.reclassify_observation(...)` |
| `storage.attachments.put(...)`               | `await storage.put_attachment(...)`         |
| `storage.attachments.reclassify(...)`        | `await storage.reclassify_attachment(...)`  |
| `storage.messages.put_message(...)`          | `await storage.put_message(...)`            |
| `storage.messages.get_by_evidence_ref(...)`  | `await storage.get_message_body(...)`       |
| `storage.linkages.insert_proposed(...)`      | `await storage.insert_proposed_linkage(...)`|
| `storage.linkages.transition(...)`           | `await storage.transition_linkage(...)`     |
| `storage.linkages.get(...)`                  | `await storage.get_linkage(...)`            |
| `storage.linkages.list_linkages(...)`        | `await storage.list_linkages(...)`          |
| `storage.personas.persona_for_actor(...)`    | `await storage.persona_for_actor(...)`      |
| `storage.personas.merge_actors(...)`         | `await storage.merge_actors_into_persona(...)` |
| `storage.personas.split_actor(...)`          | `await storage.split_actor_from_persona(...)` |
| `storage.graph.upsert_node(...)`             | `await storage.upsert_graph_node(...)`      |
| `storage.graph.upsert_edge(...)`             | `await storage.upsert_graph_edge(...)`      |
| `storage.graph.stats()`                      | `await storage.graph_stats()`               |
| `storage.vector_index.upsert_simhash(...)`   | `await storage.upsert_simhash(...)`         |
| `storage.vector_index.nearest(...)`          | `await storage.nearest_simhashes(...)`      |
| `storage.cursors.get(...)`                   | `await storage.get_cursor(...)`             |
| `storage.cursors.set(...)`                   | `await storage.set_cursor(...)`             |
| `storage.corpus.append(...)`                 | `await storage.append_corpus(...)`          |
| `storage.corpus.iter_since(...)`             | `await storage.iter_corpus_since(...)`      |
| `storage.profiles.get_current(...)`          | `await storage.get_current_profile(...)`    |
| `storage.profiles.upsert(...)`               | `await storage.upsert_current_profile(...)` |
| `storage.feedback_pairs.record(...)`         | `await storage.record_feedback_pair(...)`   |
| `storage.syslog.append(...)`                 | `await storage.append_syslog(...)`          |

**Sync → async flip.** Every method on the repository is `async def`. The legacy sync `Session(engine)` path is gone. Engines use `sqlite+aiosqlite://` + `AsyncSession`. DDL stays sync (`SQLModel.metadata.create_all` is sync-only) via a parallel `get_sync_engine` used only at boot. The `BEGIN IMMEDIATE` audit chain uses a raw aiosqlite cursor inside an `asyncio.Lock` for in-process serialization on top of SQLite's RESERVED lock for cross-process.

**Escape hatch.** `BaseRepository.session()` is an `async with` context manager yielding the main-engine `AsyncSession`. Reserved for collector-side custom transactions (Matrix edit patching, reaction insertion) that don't fit a single repo call. Production code uses it in `eyenet/collectors/matrix/real.py` exactly twice.

**Two firm rules.**

1. **No dialect leak in mixins.** The `sqlmodel_repo/` mixin layer must use only generic SQLModel ORM (SELECT-then-add/update). Dialect-specific SQL (`sqlalchemy.dialects.sqlite.insert`, `BEGIN IMMEDIATE`, `INSERT IGNORE`, `INFORMATION_SCHEMA`) lives only in the concrete backend's `repository.py`. The audit `_append_audit_locked` and the SQLite `set_cursors_bulk` upsert are the established override pattern: declared as `raise NotImplementedError` on `SQLModelRepository`, overridden on `SQLiteRepository`.

2. **Tests use `BaseRepository` + `get_repository()`, not direct `SQLiteRepository` imports.** Every test types against the abstract surface and constructs via the factory. SQLite-specific impl probes (audit `BEGIN IMMEDIATE`, init lock, pragma wiring) pin via `monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")` AND get a `_sqlite` filename suffix (`test_audit_chain_sqlite.py`, `test_init_concurrency_sqlite.py`, `test_repository_sqlite.py`). When MySQL/Postgres backends land, mirror files sit alongside (`test_audit_chain_mysql.py`, …) without collision.

**What got deleted (Phase 6).**

- `eyenet/storage/{audit,cursors,feedback,linkages,personas,syslog,vectors,messages,profiles,observations,graph,corpus,sqlite,reply_resolver,actors,engines}.py` — 16 legacy modules
- `eyenet/contracts/storage.py` — 387 lines of sub-store ABCs (`MessageStore`, `CaseStore`, `ClearanceStore`, `AuditStore`, `LinkageStore`, `PersonaStore`, `ProfileStore`, `VectorIndex`, `GraphStore`, `FeedbackPairStore`, `CorpusStore`, `ObservationStore`, `Storage` aggregate)
- 17 test files migrated, 4 renamed with `_sqlite` suffix, 1 deleted (`test_audit_drift_guard.py` — tested a legacy hand-pinned INSERT column tuple that the new SQLModel ORM path doesn't have)

**Caller migration footprint.**

| Layer            | Files migrated | Notes                                                                 |
|------------------|----------------|-----------------------------------------------------------------------|
| Production       | 14             | Every service constructor takes `storage: BaseRepository`             |
| Unit tests       | ~30            | Fixtures use `get_repository(in_memory=True)`                         |
| Integration/e2e  | ~15            | Shared `tests/_seed.py:seed_telegram_fixture` helper replaces per-test sync seed blocks |
| Total            | ~60 files      | `+1576 / −4286` lines net                                             |

**Performance notes.** Async session overhead is ~2–5 ms higher per call than the legacy sync `Session(engine)` path. The StylometricSensor dispatch loop was the worst hot spot (15 primitives × 3 sessions/primitive per envelope). The fix landed in three batched-write helpers, all generic enough to live in the mixin layer:

- `get_cursors_bulk(actor_id, primitive_names)` — single SELECT for every per-primitive cursor in one dispatch
- `put_observations_bulk(rows)` — single session for all primitives' observations
- `set_cursors_bulk(actor_id, updates)` — single transaction; SQLite override uses `INSERT ... ON CONFLICT DO UPDATE` for race safety under concurrent dispatch

Plus one repo helper: `recent_message_bodies_for_actor(actor_id, limit=N)` — the Verifier's window-corpus loader replaces a `storage._engines[StoreName.MAIN]` + raw `Session` + LIFO select pattern with one round-trip.

**Definition of done.** ruff format clean, ruff check clean, mypy `--strict` clean (275 source files, 0 errors), bandit 0 issues, deptry clean, detect-secrets clean, `pytest` 962/962 unit + 41/42 integration (1 throughput-bound flake under SQLite QueuePool pressure) + 5/5 e2e over real NATS, 18 commits squashed-or-merged as `5efbe50`.

---

### Group A — Auth & tokens

Auth is sequential *within* the group (A1 → A2 → A3 → A4 → A5 → A6), but the group as a whole is parallel-safe against B, C, D, E, F, G, H. The `messages.db` schema additions in A1 don't touch any table read by B/C/F.

#### M9.A1 — Auth tables (no handlers) ✅ SHIPPED (`b3c3926`)
- New tables in `messages.db`: `system_user_credential`, `refresh_token`, `jwt_denylist`, `system_user_scope`. STRIPS inline `password_hash` / `mfa_secret_encrypted` from `SystemUserTable`.
- Storage mixin: `eyenet/storage/sqlmodel_repo/auth.py` — `get_credential`, `set_credential`, `record_refresh_token`, `revoke_refresh_chain`, `denylist_jti`, `is_jti_denied`, `set_user_scopes`, `get_user_scopes`. ANSI SQL only; SQLite-specific UPSERT (if needed) goes on `SQLiteRepository` per CLAUDE.md §2.3 Rule 1.
- Tests in `tests/unit/storage/test_auth_sqlmodel.py` against `get_repository(in_memory=True)`.
- **Depends on:** M9.1a.5
- **Files touched:** `eyenet/models/auth.py`, `eyenet/storage/sqlmodel_repo/{__init__.py,auth.py}`, `eyenet/storage/repository.py`, `tests/unit/storage/test_auth_sqlmodel.py`
- **DoD:** new tests pass; `mypy --strict` clean; CHECK on `refresh_token.replaced_by` (replacement chain) enforced.

#### M9.A2 — JWT + login/refresh/logout/me handlers ✅ SHIPPED (`6c497cd`)
- `eyenet/api/auth/jwt.py` — RS256 sign/verify, kid rotation hooks. Access tokens carry a `typ:"access"` claim (the discriminator A5's stream tokens isolate against).
- Handlers: `/v1/auth/login`, `/refresh`, `/logout`, `/me`.
- `eyenet/api/v1/schemas/auth.py` — `LoginRequest`, `TokenPair`, `AccessToken`, `UserMe` (each with `MODELS.md §2.17` docstring per §9.5).
- `RequireScope` dependency factory + `current_user` resolver consulting `system_user_scope` AND active `system_user_clearance_grant` rows from M9.1a.
- Audit subjects: `eyenet.audit.auth.{login.success,login.failure,refresh,logout}`.
- **Depends on:** M9.A1
- **Files touched:** `eyenet/api/auth/jwt.py`, `eyenet/api/v1/{auth.py,schemas/auth.py,__init__.py}`, `eyenet/api/deps.py`
- **DoD:** login → refresh → logout round-trip; jti denylist hit on revoked token blocks reuse; Schemathesis stateful pass on the four endpoints; contract `expected_routes.json` updated.

#### M9.A3 — MFA enrollment + login challenge ✅ SHIPPED (`e0f0599`, `5f7cabb`)
- TOTP (RFC 6238): `POST /v1/auth/mfa/enroll` (provisioning URI + base32 secret), `/mfa/verify-enroll`, `/mfa/disable`. Secret Fernet-encrypted at rest under `<data_dir>/jwt/mfa_key` (0600, generated on first boot alongside the JWT keypair; rotation is a manual operator procedure per `MFA_OPS.md`).
- Login challenge: `/v1/auth/login` returns a discriminated `LoginResponse` (token pair OR `mfa_challenge_id`) — HTTP 200, not 401, because the password check itself succeeded; `POST /v1/auth/login/verify` redeems the one-shot challenge. 5-fail / 15-min lockout.
- Storage: one-shot `mfa_challenge` table in `messages.db` (≤90s TTL, replay-detected on consume); dep `pyotp>=2.9` (`cryptography` already pinned for Fernet).
- ASCII-only digit gate on the submitted code at every layer (rejects Unicode-digit lookalikes).
- Operator recovery: `eyenet user unlock-mfa` clears a lockout without touching the secret (A6 adds `reset-mfa` to wipe it). Recovery codes deferred. See `development/MFA_OPS.md`.
- Audit subjects: `eyenet.audit.auth.mfa.{enrolled,enroll_failed,verified,verify_failed,disabled,disable_failed,challenge_issued,locked_out,replay_attempt,unlocked}`.
- **Depends on:** M9.A2
- **Files touched:** `eyenet/api/auth/{_mfa.py,_mfa_key.py}`, `eyenet/api/v1/auth/api_mfa_*.py`, `eyenet/api/v1/auth/api_login_verify.py`, `eyenet/models/mfa.py` (`mfa_challenge`), `eyenet/storage/{repository.py,sqlmodel_repo/auth.py}`, `eyenet/cli/user.py`, `development/MFA_OPS.md`
- **DoD:** enroll → verify-enroll → login-challenge → verify round-trip; replay of a consumed challenge rejected; lockout after 5 fails; `unlock-mfa` clears it.

#### M9.A4 — Personal Access Token surface ✅ SHIPPED (`4f03dec`)
- New table: `personal_access_token` in `messages.db` (already declared in §16/A1 scope-list — split as own milestone for surface isolation).
- Handlers: `POST /v1/auth/tokens`, `GET /v1/auth/tokens`, `DELETE /v1/auth/tokens/{id}`.
- PAT auth path joins the same middleware as JWT (same `current_user` contract). HMAC-pepper hash at rest; the plaintext secret never reaches storage.
- `admin:tokens` scope wired.
- Audit subjects: `eyenet.audit.auth.token.{minted,revoked}`.
- M9.2-era PAT docs: copy-pasteable Prometheus least-privilege `read:metrics` scrape recipe in `development/PAT_RECIPES.md`.
- **Depends on:** M9.A2 (MFA enforcement on PAT mint is optional per-operator; gated on the calling user's MFA status, not on A3 shipping)
- **Files touched:** `eyenet/models/auth.py` (PAT table), `eyenet/storage/sqlmodel_repo/auth.py` (PAT helpers), `eyenet/api/v1/auth_tokens.py`, `eyenet/api/v1/schemas/tokens.py`, `development/PAT_RECIPES.md`
- **DoD:** PAT mint → use → revoke round-trip; PAT-scoped scrape against `/v1/metrics` works once M9.I3 lands (forward compat OK).

#### M9.A5 — Stream-token + EventSource fallback ✅ SHIPPED (`783ea9b`)
- `POST /v1/auth/stream-token` mints a **stateless** RS256 stream JWT (`typ:"stream"`, ≤15-min `exp`, frozen `topics`) for browser `EventSource`, which cannot set an `Authorization` header — the token rides in a `?token=` query param.
- The `typ` discriminator isolates the two surfaces: an access token presented in `?token=` and a stream token presented on `Authorization` both 401.
- Mint gate: each requested topic's `stream:*` scope must be in the caller's live `effective_scopes` (403 otherwise). `get_stream_principal` is wired into all five `/v1/stream/*` endpoints, so the EventSource auth path is LIVE (401 on bad/expired/wrong-type token); the SSE *delivery* bodies still raise 501 pending a later streaming milestone.
- Revocation is expiry only — ephemeral by design, no denylist. See `development/STREAM_TOKENS.md` and §6.4.2.
- **Depends on:** M9.A2
- **Files touched:** `eyenet/api/auth/_jwt.py`, `eyenet/api/v1/auth/api_stream_token.py`, `eyenet/api/v1/stream/*`, `eyenet/api/deps.py`, `development/STREAM_TOKENS.md`
- **DoD:** mint → use on `/v1/stream/*?token=` passes auth (501, delivery pending); access-as-stream and stream-as-access both 401; VIEWER mint 403; ANALYST denied audit/control topics.

#### M9.A6 — User-management CLI ✅ SHIPPED (`62b5a99`)
- `eyenet user create`, `reset-password`, `scopes {grant,revoke,list}`, `reset-mfa` — alongside A3's `unlock-mfa`.
- **Authorizer gate** on every mutating command: `--as <username>` + hidden password prompt (argon2id verify) + conditional TOTP step-up (only when the authorizer is MFA-enrolled) + must hold `admin:users`. Possession of a privileged credential — not mere shell access — is required to mutate system users. Bootstrap exception: the first `create` on an empty user table is ungated and forced to `--role admin`.
- `scopes grant` refuses the grant-only `ClearanceScope` values (→ exit 5, pointing at the time-bound clearance-grant path); `grant`/`revoke` best-effort publish `eyenet.auth.scopes_changed` for cross-process cache eviction (warns + continues if NATS is unreachable).
- Passwords via hidden confirmation prompt or `--generate` (printed once); no `--password` flag, so nothing sensitive lands in argv/history.
- Same audit shape as the API handlers (no CLI/API divergence): `eyenet.audit.auth.{user.created,password.reset,scopes.granted,scopes.revoked,mfa.reset}`.
- **Depends on:** M9.A1 (tables), M9.A3 (MFA helpers for the step-up)
- **Files touched:** `eyenet/cli/user.py`, `eyenet/storage/{repository.py,sqlmodel_repo/users.py}` (`count_system_users`), `tests/unit/cli/*`
- **DoD:** create → set scopes → reset password round-trip; emitted audit rows match the API path; `eyenet/cli/user.py` at 100% line+branch.

---

### Group B — File-access journal

Fully independent of A. Different tables (`audit.db`), different handler module, no shared schemas.

#### M9.B1 — Signing pubkey history + acknowledgments
- Tables in `audit.db`: `system_user_signing_pubkey_history`, `file_access_acknowledgment` (§5.7) — 60s nonce TTL, single-use, reason ≥16 chars.
- Storage mixin: `eyenet/storage/sqlmodel_repo/file_access.py` — `record_signing_key`, `lookup_key_by_fingerprint`, `record_acknowledgment`, `consume_acknowledgment`.
- Ed25519 verification helpers (`cryptography` lib).
- **Depends on:** M9.1a.5
- **Files touched:** `eyenet/models/file_access.py`, `eyenet/storage/sqlmodel_repo/file_access.py`, `eyenet/storage/repository.py`, `tests/unit/storage/test_file_access_keys.py`
- **DoD:** fingerprint reproduces `sha256(verifying_key_DER)[:8]`; expired nonce rejected; double-spend rejected.

#### M9.B2 — file_access_journal table + signing
- Table `file_access_journal` (§5.6) with the mandatory Ed25519 signature column, CHECK enforcing tier-conditional fields.
- Helper `record_access(serving_user, content_hash, tier, request_ctx) -> JournalRow` that signs the canonical form and persists.
- `verify_signature(row)` for post-hoc audit.
- **Depends on:** M9.B1
- **Files touched:** `eyenet/storage/sqlmodel_repo/file_access.py` (extend), `tests/unit/storage/test_file_access_journal.py`
- **DoD:** tampering with `served_at` invalidates the signature; chronological exoneration query returns ordered signed rows.

#### M9.B3 — Byte-serving handlers + exoneration query
- Handlers: `GET /v1/attachments/{hash}` (tier-aware), `GET /v1/audit/file-access` (exoneration query).
- §5.9 audit subjects emitted on every byte-fetch path.
- **Depends on:** M9.B2, M9.A2 (needs `current_user`)
- **Files touched:** `eyenet/api/v1/attachments.py`, `eyenet/api/v1/audit_file_access.py`
- **DoD:** restricted/classified fetch requires acknowledgment + grant; signed row materialized before bytes flow; exoneration query for a given `user_id` returns chronologically-ordered signed rows.

---

### Group C — Discovery storage (multidomain Sources, collectors, candidates)

Independent of A, B, F, G, H. Lands the schema half of every concept modelled this design pass (MODELS.md §2.19–§2.27). Group C is the dependency for D (API) and E (runtime), but C-internal milestones can be parallelized into 2–3 worktrees if two operators want to split the load.

#### M9.C1 — SourceDomain table + normalize_host invariant ✅ SHIPPED (`d3735ac`)
- New table: `SourceDomain` (MODELS.md §2.26) with `pattern_kind ∈ {exact, subdomain_wildcard, suffix_match}`, partial-unique `is_primary` per source, soft-delete `removed_at`.
- Helper: `eyenet/util/domain.py` with `normalize_host(input: str) -> str` — IDN/punycode normalize, strip trailing dot, lowercase, reject empty/whitespace, reject `xn--` *AND* unicode (must be one canonical form).
- Storage mixin: `eyenet/storage/sqlmodel_repo/sources.py` — `add_source_domain`, `remove_source_domain` (soft), `find_source_for_host`, `detect_overlap(pattern, pattern_kind)`.
- Overlap detection runs **in-transaction**, before insert, against all non-removed rows — refuses ambiguous overlaps with a typed `SourceDomainOverlapError(conflicting_id, conflict_kind)`.
- **Depends on:** M9.1a.5
- **Files touched:** `eyenet/models/source_domain.py`, `eyenet/util/domain.py`, `eyenet/storage/sqlmodel_repo/sources.py`, `eyenet/storage/repository.py`, `tests/unit/storage/test_source_domains.py`, `tests/unit/util/test_normalize_host.py`
- **DoD:** homograph test pairs collide on `normalize_host` (`раура.com` vs `paypa.com` — Cyrillic а vs Latin a); overlap conflict raises before INSERT; primary swap is atomic.

#### M9.C2 — Source refactor (canonical_url → SourceDomain.is_primary) ✅ SHIPPED (`feeb22c`)
- `Source.base_url` renamed to `canonical_url`, display-only, enforced by CHECK referencing the primary `SourceDomain` row (MODELS.md §1.1).
- `eyenet init` seed updates Telegram/Matrix sources with the corresponding primary domains.
- **Depends on:** M9.C1
- **Files touched:** `eyenet/models/source.py`, `eyenet/cli/init.py`, `tests/unit/storage/test_source_canonical_url.py`
- **DoD:** `rm data/*.db && eyenet init` produces a clean main.db with seeded sources + primary domains; canonical_url change without matching primary domain is rejected.

#### M9.C3 — Collector table (storage only, no supervisor yet) ✅ SHIPPED (`d94445f`)
- New table: `Collector` (MODELS.md §2.19) — `source_id`, `identity_id UNIQUE`, `kind`, `config JSON`, `desired_state`, `observed_state`, soft-delete.
- Storage mixin: `eyenet/storage/sqlmodel_repo/collectors.py` — `create_collector`, `list_collectors`, `set_desired_state`, `record_observed_state`, `redact_config` (returns config with sensitivity-flagged keys masked).
- `Identity.role ∈ {monitor, scout, quarantine}` enum extension.
- **Depends on:** M9.1a.5
- **Files touched:** `eyenet/models/collector.py`, `eyenet/models/identity.py` (role extension), `eyenet/storage/sqlmodel_repo/collectors.py`, `eyenet/storage/repository.py`, `tests/unit/storage/test_collectors.py`
- **DoD:** `identity_id` uniqueness enforced (one identity = one collector); redacted config matches §4.11 sensitivity contract; desired/observed state transitions tested.

#### M9.C4 — GroupCandidate + GroupCandidateMention storage ✅ SHIPPED (`4416c86`)
- Tables: `GroupCandidate` (MODELS.md §2.20) — 8-state machine `discovered→queued→approved→joining→joined/rejected/failed/parked`. `GroupCandidateMention` (§2.21) with `seed_root_id`, `depth_from_root`.
- Storage mixin: `eyenet/storage/sqlmodel_repo/candidates.py` — `record_candidate_mention` (upserts candidate, appends mention), `list_queued_candidates`, `transition_candidate` (state guard), `compute_eligibility_inputs` (returns reachable roots, active memberships, available scouts for a candidate).
- State transitions audited.
- **Depends on:** M9.C1 (`source_id` FK), M9.C3 (eligibility needs `Collector`)
- **Files touched:** `eyenet/models/candidates.py`, `eyenet/storage/sqlmodel_repo/candidates.py`, `tests/unit/storage/test_candidates.py`
- **DoD:** every illegal transition raises; mention upsert is idempotent on `(candidate_id, evidence_ref)`; `depth_from_root` materialized correctly across multi-hop chains.

#### M9.C5 — CollectorGroupMembership + MessageObservation ✅ SHIPPED (`d2fc512`)
- Tables: `CollectorGroupMembership` (§2.22) — `joined_via` discriminator, `left_at`/`left_reason`. `MessageObservation` (§2.23) — `was_first_sighting` materialized per `(message_evidence_ref, collector_id)`.
- Storage mixin: `eyenet/storage/sqlmodel_repo/memberships.py` — `open_membership`, `close_membership`, `list_active_memberships`, `record_observation` (atomically sets `was_first_sighting` based on existing rows for the same `evidence_ref`).
- **Depends on:** M9.C3
- **Files touched:** `eyenet/models/membership.py`, `eyenet/storage/sqlmodel_repo/memberships.py`, `tests/unit/storage/test_memberships.py`
- **DoD:** two collectors recording the same `evidence_ref` → first gets `was_first_sighting=True`, second gets `False`; race tested via `asyncio.gather`.

#### M9.C6 — GroupAccessArtifact + InfrastructureArtifact bridge ✅ SHIPPED (`83436f8`)
- New table: `GroupAccessArtifact` (§2.24) — `kind ∈ {public_identifier, invite_link, qr_code, direct_invite, paid_subscription, access_blocked, restricted_other}`, `kind_preference` ordering.
- Extension: `InfrastructureArtifact.resolved_to_source_id` + `.resolution_state` (§2.7 extension).
- Bridge resolution invariant (§2.25) lives in `sqlmodel_repo/artifacts.py` — Path A (artifact-write side) and Path B (source-create side) both fire inside the same transaction that creates the artifact or source. No async job, no operator tool.
- **Depends on:** M9.C1
- **Files touched:** `eyenet/models/{access_artifact.py,infrastructure_artifact.py}`, `eyenet/storage/sqlmodel_repo/artifacts.py`, `tests/unit/storage/test_bridge_resolution.py`
- **DoD:** creating an `InfrastructureArtifact` whose host matches an existing primary `SourceDomain` immediately populates `resolved_to_source_id` (Path A); creating a new `Source` retroactively resolves any prior unresolved artifacts whose hosts now match (Path B); both verified under `asyncio.gather` concurrency.

---

### Group D — Discovery API surface

Depends on C (storage), parallel to E (runtime). Surface map §3.7–§3.9, contracts §4.11–§4.13.

**As-built (M9.D1–D3 ✅ SHIPPED on `worktree-groupD-discovery-api`; D4 deferred).**
Slice commits: storage gaps `cd7c9f2`, D1 `558b7f5`, D2 `1dee40c`, D3 `a2b94f6`.
One operation per `api_<verb>_<noun>.py` (NOT the single-file `sources.py`/`collectors.py`/
`candidates.py` the "Files touched" lines below predate). Deviations, all grounded in
Group C's actual storage surface + documented in code:
- **D1:** `DELETE /v1/sources/{id}` deferred (needs `delete_source` + multi-table FK guard);
  atomic initial-`domains[]` in POST deferred (`add_source_domain` commits per call → add
  domains individually); `?force`/`?hard` overlap-bypass + domain-notes PATCH deferred.
  Added storage `update_source` (display_name/notes) — Group C only shipped canonical-url.
- **D2:** `pause` dropped (no PAUSED in `CollectorDesiredState`); `?include_left` historical
  memberships deferred (no closed-membership read); config validated as opaque kind-tagged
  dict (discriminated union deferred). start/stop → 202 + CollectorDetail.
- **D3:** **eligibility is a STUB** — `eligibility_for_candidate` returns
  `DEFERRED_TO_RUNTIME` per mentioning collector; `approve` does NOT gate on it (validates
  existence + assigned_collector_id + legal transition only — operator-trusted pending Group
  E). Added `FAILED→QUEUED` to the transition map (the retry edge Group C omitted).
  Transitions → 202 + CandidateDetail (audit.emit returns None → no WriteAccepted event_id).
- Scopes added to baselines: `read:sources`+`write:sources`, `read:collectors`+`write:collectors`,
  `read:candidates`+`write:candidates` (ANALYST+ADMIN); grant-only: `admin:sources`,
  `read:collectors_config`, `admin:collectors`, `admin:candidates`. Surface pinned in
  `contracts/openapi/eyenet.v1.yaml`; ASGI smoke in `tests/integration/api/test_discovery_surface.py`.

#### M9.D1 — Sources + SourceDomains handlers ✅ SHIPPED (`558b7f5`)
- Handlers under §4.13: `GET/POST/PATCH/DELETE /v1/sources`, `GET/POST/PATCH/DELETE /v1/sources/{id}/domains`. Atomic bulk-create for domains. 409 conflict shape for overlap.
- Schemas in `eyenet/api/v1/schemas/sources.py` with `MODELS.md §1.1 / §2.26` docstrings.
- Audit subjects: `eyenet.audit.source.{created,updated,deleted}`, `eyenet.audit.source_domain.{added,removed,primary_swapped}`.
- **Depends on:** M9.C2, M9.A2
- **Files touched:** `eyenet/api/v1/sources.py`, `eyenet/api/v1/schemas/sources.py`
- **DoD:** overlap-conflict returns 409 with `conflicting_domain_id`; pattern + pattern_kind immutable post-create (remove + re-add path enforced); Schemathesis stateful pass.

#### M9.D2 — Collectors handlers ✅ SHIPPED (`1dee40c`)
- Handlers under §4.11: `GET/POST/PATCH/DELETE /v1/collectors`, `POST /v1/collectors/{id}/start|stop|pause`.
- Config redaction per §4.11 sensitivity contract.
- SystemLog event taxonomy emitted on every supervisor-driven transition.
- **Depends on:** M9.C3, M9.A2
- **Files touched:** `eyenet/api/v1/collectors.py`, `eyenet/api/v1/schemas/collectors.py`
- **DoD:** create → start → pause → stop → delete round-trip; redacted config never leaks `telegram_api_hash`; SystemLog rows materialized.

#### M9.D3 — Candidates triage handlers ✅ SHIPPED (`a2b94f6`) — eligibility STUB
- Handlers under §4.12: `GET /v1/candidates`, `GET /v1/candidates/{id}` (with per-collector eligibility precomputed), `POST /approve|reject|park|retry`.
- Eligibility predicate from §4.12.3 lives in `eyenet/services/discovery/eligibility.py`.
- **Depends on:** M9.C4, M9.C5, M9.D2
- **Files touched:** `eyenet/api/v1/candidates.py`, `eyenet/api/v1/schemas/candidates.py`, `eyenet/services/discovery/eligibility.py`
- **DoD:** approve with ineligible collector rejected with reason code; precomputed `eligibility_per_collector` matches the predicate run server-side; Schemathesis stateful pass.

#### M9.D4 — Seed-roots + Case.auto_join_policy — ◑ MODEL+STORAGE SHIPPED with Group E; HTTP endpoints DEFERRED
- The **Case model + storage fold-in landed with Group E slice 0** (the real §4.12.3
  eligibility predicate needs `Case.redundancy_policy` + candidate→Case resolution).
  `case_v2` gained `seed_root_group_ids` / `redundancy_policy` / `auto_join_policy` /
  `auto_join_score_threshold` (+ `RedundancyPolicy`/`AutoJoinPolicy` enums); storage
  `update_case_discovery_policy` (emits `case.seed_roots_changed`) +
  `resolve_case_for_candidate`. *No Alembic — `rm data/*.db && eyenet init`.*
- The **eligibility recompute is live**: a seed-root change shifts
  `reachable_roots_for_collector`, so the next `GET /v1/candidates/{id}` reflects it
  (the predicate is computed at read time, not cached) — the original DoD is met.
- **Still DEFERRED — the HTTP endpoints** `GET/PUT /v1/cases/{id}/seed-roots`,
  `POST /v1/cases/{id}/seed-roots/{group_id}`. They sit on the `/v1/cases` tree whose
  CRUD handlers are still `NotImplementedError` stubs (a separate Case-API group). The
  storage + model they need is done; wiring the operator-facing surface is a thin
  follow-on once `/v1/cases` CRUD lands.
- **Files touched (as built):** `eyenet/models/case.py`, `eyenet/contracts/{case,enums}.py`,
  `eyenet/storage/sqlmodel_repo/{cases,candidates}.py`.

---

### Group E — Discovery runtime — ✅ E1–E4 SHIPPED; E5 DEFERRED

Depends on C (storage), parallel to D (API). Sensor primitives + supervisor + scout pipeline + Telegram-layer recursion.

**As-built deviations (whole group):** the discovery extractors live under a NEW
`eyenet/sensor/discovery/` seam (`DiscoveryExtractor` ABC + resolved `MessageContext`),
NOT `eyenet/sensor/primitives/` — the stylometric primitives are pure
`compute(corpus,bodies)→Observation`, while discovery extractors write storage per
message with collector/group context. The live `DiscoverySensor` resolves a
`RawMessageEnvelope` → `MessageContext` (collector via a new
`resolve_collector_by_instance_id` reverse-lookup since the 8-char `instance_id`
isn't stored on `CollectorTable`; actor via `resolve_actor_id`; group + lineage via
`upsert_group`/`group_lineage`). The **DB `IdentityTable` is the source of truth for
the discovery-loop role/state/graduation machine**; the file pool stays the
credential store; the file↔DB provisioning bridge is deferred to E5.

#### M9.E1 — `url_extraction` discovery extractor — ✅ SHIPPED
- `eyenet/sensor/discovery/url_extraction.py` — extracts scheme-qualified URLs + bare
  onion addresses, `normalize_host`-collapses unicode↔punycode dupes to one artifact,
  classifies onion vs domain, upserts via `put_infrastructure_artifact` (Path-A inline).
- **Files (as built):** `eyenet/sensor/discovery/{_base,url_extraction}.py`, `tests/unit/sensor/test_url_extraction.py`
- **DoD met:** punycode collapse + resolved/unresolved branches tested.

#### M9.E2 — `channel_reference_extraction` discovery extractor — ✅ SHIPPED
- `eyenet/sensor/discovery/channel_reference_extraction.py` — Telegram t.me invite/public/@handle + Matrix `#room:server` → `record_candidate_mention`; depth = observed-group depth + 1 with inherited seed root; storage-idempotent on `{evidence_ref}#{ref}`. Plus the frozen deterministic `score_candidate` (distinct groups/actors) + `discovered→queued` auto-queue (auto-*approve* stays off by default).
- **Files (as built):** `.../channel_reference_extraction.py`, `eyenet/sensor/discovery_sensor.py`, `tests/unit/sensor/test_channel_reference_extraction.py`, `tests/integration/test_discovery_sensor.py`
- **DoD met:** idempotent mention + depth propagation tested end-to-end.

#### M9.E3 — CollectorSupervisor + real eligibility predicate — ✅ SHIPPED
- `eyenet/services/collector_supervisor.py` (`ServiceBase`, in-process async, NOT a flag-watcher). Tick-driven: reconciles `observed_state`→`desired_state` (crash-safe by polling, audited `collector.reconciled`); dispatches approved candidates — real §4.12.3 eligibility gate, leases a scout (`lease_scout`, single writer of `state=in_use`), writes `approved→joining`, records a `JoinGroupCommand` in the `candidate.joining` audit payload.
- **Retires the D3 eligibility stub**: `eyenet/services/discovery/eligibility.py` now implements dedup/redundancy + depth + scout-availability; `GET /v1/candidates/{id}` surfaces real verdicts.
- **Files (as built):** `eyenet/services/collector_supervisor.py`, `eyenet/services/discovery/eligibility.py`, `eyenet/contracts/supervisor.py`, `tests/{unit/services/test_eligibility,integration/services/test_supervisor}.py`
- **DoD met:** desired/observed reconcile, crash-resume, identity-lease invariant tested.
- **Deferred to E5:** the actual platform join (`joining→joined`) + the command's bus dispatch.

#### M9.E4 — Scout graduation pipeline — ✅ SHIPPED
- `eyenet/services/discovery/scout_graduation.py` (`ServiceBase`, hourly tick). `graduate_due` promotes SCOUTs past the observation window (default 7d, still-active membership = clean window) → MONITOR + `graduated_at` + `identity.graduated`. `quarantine_scout` (burn path) → BURNED/QUARANTINE + park candidate + `identity.burned`; live ban-detection trigger is E5.
- **Files (as built):** `eyenet/services/discovery/scout_graduation.py`, `eyenet/storage/...list_graduating_scouts`, `tests/integration/services/test_scout_graduation.py`
- **DoD met:** graduate / too-fresh / burn+park tested.
- **Deviation:** window is a service default; per-source `Source.scout_observation_window_days` override deferred with the other `Source.default_*` discovery fields.

#### M9.E5 — Telegram collector recursion — ⏸ DEFERRED (needs a live Telethon client)
- Lands after E1–E4; the collector consuming `JoinGroupCommand`, the platform join, `joining→joined`, FloodWait/InviteExpired mapping. Coverage-omitted live-service code (CLAUDE.md §3.4). Also closes the file↔DB identity bridge + the live scout-burn trigger.
- Telegram collector consumes approved `GroupCandidate` rows, joins via the access artifact's `kind_preference`-ordered method list, opens `CollectorGroupMembership`, transitions candidate to `joined`.
- Cross-source candidates (`source_id != collector.source_id`) remain inert per §4.12.10 deferred-items note.
- **Depends on:** M9.D3 (approval surface), M9.E2 (candidates being populated), M9.E3 (supervisor)
- **Files touched:** `eyenet/collectors/telegram/real.py` (extend), `eyenet/collectors/telegram/discovery.py` (new)
- **DoD:** approved candidate → joined Group with `discovered_via_candidate_id` populated; depth-from-root respected; access blocked → candidate transitions to `failed` with reason.

---

### Group F — Read surface

Depends on M9.1a only. Fully parallel to A, B, C, D, E, G, H. Surface §3.2, §3.3.

#### M9.F1 — Actors + Personas read endpoints
- `GET /v1/actors`, `/v1/actors/{id}`, `/v1/personas`, `/v1/personas/{id}`.
- Schemas in `eyenet/api/v1/schemas/{actors.py,personas.py}` with `from_domain` translator + `MODELS.md` docstring per §9.5.
- **Depends on:** M9.1a.5, M9.A2
- **Files touched:** `eyenet/api/v1/{actors.py,personas.py,schemas/actors.py,schemas/personas.py}`
- **DoD:** Schemathesis pass; cursor pagination wired (depends on M9.F5 for shared `CursorPage`).

#### M9.F2 — Linkages read endpoints
- `GET /v1/linkages` (summary), `GET /v1/linkages/{id}` (detail).
- **Depends on:** M9.1a.5, M9.A2
- **Files touched:** `eyenet/api/v1/linkages_read.py`, `eyenet/api/v1/schemas/linkages.py`
- **DoD:** Schemathesis pass.

#### M9.F3 — Graph read endpoints
- `GET /v1/graph/neighbors`, `GET /v1/graph/stats`.
- **Depends on:** M9.1a.5, M9.A2
- **Files touched:** `eyenet/api/v1/graph.py`, `eyenet/api/v1/schemas/graph.py`
- **DoD:** Schemathesis pass.

#### M9.F4 — Audit read endpoints + verify
- `GET /v1/audit`, `GET /v1/audit/verify`. Chain verification reads the full audit table and recomputes `self_hash`.
- **Depends on:** M9.1a.5, M9.A2
- **Files touched:** `eyenet/api/v1/audit.py`, `eyenet/api/v1/schemas/audit.py`
- **DoD:** verify returns OK on clean chain; tampering with one row's `self_hash` returns the offending row + index.

#### M9.F5 — Pagination + enum query params
- Shared `eyenet/api/v1/schemas/pagination.py` (`CursorPage[T]`, `OpaqueCursor`).
- Enum-typed query param helpers used by F1–F4.
- **Depends on:** M9.0
- **Files touched:** `eyenet/api/v1/schemas/pagination.py`, `eyenet/api/deps_paging.py`
- **DoD:** cursor round-trip stable across F1–F4 endpoints; opaque cursor opaque-but-stable.

#### M9.F6 — evidence_access audit middleware
- Middleware emits per-subject audit row BEFORE response body is written. Failure to write audit → 503 (gate, per §5.5).
- **Depends on:** M9.F1, M9.F2, M9.F3, M9.F4 (covers every read path)
- **Files touched:** `eyenet/api/middleware/evidence_access.py`
- **DoD:** every read endpoint produces matching audit row; storage outage on append → 503 (no body served).

#### M9.F7 — query_api deletion
- `eyenet/query_api/` deleted in one commit. All callers redirected to `/v1/`.
- **Depends on:** M9.F1, M9.F2, M9.F3, M9.F4
- **Files touched:** `eyenet/query_api/` (delete), various caller sites
- **DoD:** `grep -r 'from eyenet.query_api' eyenet/ tests/` empty; CI green.

---

### Group G — Write surface

Depends on M9.1a only. Parallel to F. Surface §3.4.

#### M9.G1 — Idempotency-Key middleware + idempotency_record table
- New table `idempotency_record` (`key`, `request_hash`, `response_status`,
  `response_body`, `bus_state`, `system_user_id`, `created_at`, `expires_at`).
  **`response_hash` alone (original sketch) cannot replay the stored response —
  §10.3 requires returning the original body verbatim, so we persist
  `response_status` + `response_body`** (revised 2026-09-21).
- Middleware enforces a **7d** idempotency window (per §15 resolution).
  Mismatched request body under a live key → 409.
- **Depends on:** M9.1a.5
- **Files touched:** `eyenet/models/idempotency.py`, `eyenet/storage/sqlmodel_repo/idempotency.py`, `eyenet/api/middleware/idempotency.py`
- **DoD:** duplicate POST returns first response; tampered POST returns 409.

#### M9.G2 — Event log tables
- New tables: `linkage_event_log`, `persona_event_log`, `identity_event_log` (§11.5). Every state transition writes one row with `traceparent`.
- Storage helpers in `eyenet/storage/sqlmodel_repo/event_logs.py`.
- **Depends on:** M9.1a.5
- **Files touched:** `eyenet/models/event_logs.py`, `eyenet/storage/sqlmodel_repo/event_logs.py`
- **DoD:** transition write atomic with state mutation; `traceparent` propagated through.

#### M9.G3 — Linkage write handlers
- `POST /v1/linkages/{id}/confirm|reject` with `LinkageDecisionRequest`.
- Writes follow §5.5 / §10.3 durability rule: durable audit append → durable event-log append → async bus publish.
- CLI parity with `eyenet linkage confirm/reject`.
- **Depends on:** M9.G1, M9.G2, M9.A2
- **Files touched:** `eyenet/api/v1/linkages_write.py`, `eyenet/api/v1/schemas/writes.py`
- **DoD:** API and CLI emit byte-identical audit rows; bus publish failure does NOT roll back storage.

#### M9.G4 — Persona write handlers
- `POST /v1/personas/{id}/merge|split` per the **§4.10a persona action model**.
  Net-new surface (not in the M9.0 skeleton) — new `personas/` write dir + YAML
  paths + `expected_routes.json` entries. `write:persona_decision` scope.
- **Depends on:** M9.G1, M9.G2, M9.A2
- **Files touched:** `eyenet/api/v1/personas/api_{merge,split}_persona.py`,
  `eyenet/api/v1/schemas/personas.py`, Graph consumer in `eyenet/graph/graph.py`.
- **DoD:** merge/split round-trip; persona_event_log row materialized; Graph
  applies and emits `attribution.persona.updated`.

#### M9.G5 — Identity write handlers
- `POST /v1/identities/{id}/{claim,release,freeze,burn}` + `/freeze_all` per
  `IdentityActionRequest` — the authoritative §3.4 verb set
  (claim/release/freeze/burn/freeze_all), reconciled 2026-09-21. `freeze` and
  `burn` are net-new skeletons; claim/release/freeze_all fill existing ones.
- **Depends on:** M9.G1, M9.G2, M9.A2
- **Files touched:** `eyenet/api/v1/identities/api_*.py`.
- **DoD:** state transitions guarded; supervisor (M9.E3, when present) sees
  `desired_state` change via storage. Identity writes persist `desired_state`
  durably **in the handler** (documented invariant-#2 exception — no live
  applier yet; an operator must be able to freeze/burn a compromised identity
  immediately).

#### M9.G6 — /v1/audit/verify as CI gate for write Schemathesis runs
- Schemathesis stateful runs include the full write cycle and END every run with `GET /v1/audit/verify`. Chain must verify clean.
- **Depends on:** M9.G3, M9.G4, M9.G5, M9.F4
- **Files touched:** `tests/contract/api/test_write_chain_integrity.py`
- **DoD:** CI fails if any write-cycle run leaves a forked or gapped chain.

---

### Group H — SSE streaming

Depends on G (event logs). Parallel to F.

#### M9.H1 — StreamReplaySource storage abstraction
- `eyenet/api/streaming/replay.py` — `StreamReplaySource` reads from event-log tables (M9.G2), exposes `replay(after=event_id)`. Bus-agnostic.
- **Depends on:** M9.G2
- **Files touched:** `eyenet/api/streaming/replay.py`
- **DoD:** replay against MemoryBus, NATS-core, JetStream all produce identical event sequences.

#### M9.H2 — Last-Event-ID resume
- SSE handlers consult `Last-Event-ID`, invoke `source.replay(after=...)` until drained, then switch to bus live-tail with overlap dedup by event id.
- **Depends on:** M9.H1
- **Files touched:** `eyenet/api/streaming/handler.py`
- **DoD:** kill stream mid-tail, reconnect with Last-Event-ID, receive every missed event exactly once.

#### M9.H3 — Heartbeats + backpressure
- Heartbeat tick. `stream.gap` / `stream.backpressure` / `stream.expired` events.
- Per-topic backpressure buffer with high-water mark.
- **Depends on:** M9.H1
- **Files touched:** `eyenet/api/streaming/heartbeat.py`, `eyenet/api/streaming/backpressure.py`
- **DoD:** slow consumer triggers `stream.backpressure`; consumer disconnect → `stream.expired`; long idle → `stream.gap` sentinel events.

#### M9.H4 — Custom SSE OTel middleware
- Disable stock FastAPI OTel SSE instrumentation (per §11.4.1). Install connection-event-log + per-event-delivery-span model.
- **Depends on:** M9.H2
- **Files touched:** `eyenet/api/middleware/sse_otel.py`
- **DoD:** Jaeger E2E shows connection span ⊇ per-event delivery spans; stock instrumentation absent from trace tree.

#### M9.H5 — Per-topic stream handlers
- `/v1/stream/linkages`, `/personas`, `/audit`, `/control`, `/all`.
- `eyenet/api/v1/schemas/stream.py` with per-event payload models; OpenAPI `x-eyenet-sse-events` extension; TypeScript discriminated-union codegen.
- **Depends on:** M9.H2, M9.H3, M9.H4
- **Files touched:** `eyenet/api/v1/stream/*.py`, `eyenet/api/v1/schemas/stream.py`
- **DoD:** TS codegen produces typed event handler; each stream subject Schemathesis-stateful tested.

---

### Group I — Hardening (final)

Depends on F + G + H. Sequence within group is not strict — each milestone touches a different file family.

#### M9.I1 — Sliding-window rate limit ✅ (partial — see §12.3)
- Per-token sliding-window rate limit middleware. Configurable per-scope.
- **Depends on:** M9.A2
- **Files touched:** `eyenet/api/middleware/rate_limit.py`
- **DoD:** quota exhaustion → 429; window slides correctly across clock skew. ✅
- **Shipped:** global in-memory limiter (meets DoD). **Deferred:** per-surface
  floors + `rate_limit_bucket` storage backing (§12.3 upgrade path).

#### M9.I2 — CORS + X-Forwarded-For ✅
- CORS for configured operator-UI origins. ✅ (`cors.py`; env `EYENET_API_CORS_ORIGINS`)
- `X-Forwarded-For` middleware gated by `EYENET_API_TRUST_PROXY_HEADERS=1`. ✅ (`xff.py`)
- **Also (§12.5):** `/v1/openapi.json` gated behind `read:graph` (`meta/api_openapi.py`).
- **Depends on:** M9.0
- **Files touched:** `eyenet/api/middleware/{cors.py,xff.py}`
- **DoD:** preflight passes for allowed origin; XFF parsed only when env flag set.

#### M9.I3 — /v1/metrics Prometheus endpoint
- `/v1/metrics` (§11.7), opt-in via `EYENET_API_METRICS_ENABLED=1`, scope-gated `read:metrics`.
- View filters strip high-cardinality labels per §11.7.3.
- Cardinality contract test in `tests/contract/api/`.
- Example Grafana dashboard in `operations/dashboards/` (marketing-grade polish per session-saved feedback memory).
- Prom alert rules in `operations/alerts/`.
- **Depends on:** M9.A4 (PAT for scrape)
- **Files touched:** `eyenet/api/v1/metrics.py`, `operations/dashboards/eyenet-overview.json`, `operations/alerts/eyenet.yml`
- **DoD:** scrape via PAT works; cardinality contract test green; dashboard renders in Grafana without empty panels.

#### M9.I4 — TypeScript client codegen + load test
- TypeScript client codegen pipeline (artifact only — UI lives elsewhere).
- Load test profile in `tests/load/api/`.
- **Depends on:** M9.F7, M9.G6, M9.H5
- **Files touched:** `clients/typescript/`, `tests/load/api/`
- **DoD:** TS client compiles against `/v1/openapi.json` without manual fixups; load test runs against a local instance.

#### M9.I5 — Coverage gate raised
- Coverage gate raised from 0.845 (M8 floor) to 0.89.
- **Depends on:** M9.I4 (last code-adding milestone)
- **Files touched:** `pyproject.toml`, `.githooks/lib/coverage.sh` (baseline)
- **DoD:** `pytest --cov-fail-under=0.89` green.

---

### 16.1 Batching policy — group = worktree, slice = commit

The 38 sized slices in Groups A–I are not 38 PRs. The default execution pattern is:

> **One group = one worktree = one PR. Each slice inside the group is one commit in that PR's series.**

Concretely:

- Worktree name mirrors the group: `.claude/worktrees/groupA-auth-tokens`, `groupC-discovery-storage`, `groupF-read-surface`, etc.
- Commits inside the worktree carry the slice id in the subject: `feat(api): M9.A2 — JWT + login/refresh/logout/me handlers`.
- Each commit must independently satisfy its slice's `DoD:` before the next commit lands. Slice DoD becomes a commit-level gate, not a PR-level gate. This preserves bisectability — `git bisect` lands on the slice boundary that broke things.
- The full pre-merge battery (ruff format + check, `mypy --strict`, bandit, detect-secrets, deptry, full pytest with `EYENET_E2E=1` if NATS is available) runs at the **last commit** of the series, before `ExitWorktree(action="keep")` and the `--no-ff` merge.
- Merge message names the group: `Merge Group A: auth & tokens (M9.A1..M9.A6)`.

**Why this beats both extremes:**

| Alternative                       | What it costs                                                                 |
|-----------------------------------|-------------------------------------------------------------------------------|
| One worktree per slice (38 PRs)   | 38× the merge ceremony; same files touched in adjacent slices ping-pong between worktrees; reviewer fatigue. |
| One worktree per Group A..I bag → squash-merged | Loses slice boundaries in history; `git bisect` can no longer pin regressions to a single slice; review reads as one giant diff. |
| **Group = worktree, slice = commit (this policy)** | One PR per coherent feature; per-slice bisectability preserved; one merge collision on shared files like `expected_routes.json` per group, not per slice. |

**Carve-outs — when to break the rule:**

1. **Solo-operator parallelism.** When *you* are the only operator, batch by group (9 worktrees over the M9 chain, not 38). When two operators are working concurrently, slice-level worktrees on different groups are fine, and slice-level worktrees on the *same* group are fine if the `Files touched:` sets are disjoint (e.g. M9.E1 ‖ M9.E2 — the two sensor primitives touch zero common files).
2. **Hot slices.** A security-grade fix to an already-merged slice (e.g. a CVE patch on M9.A4 after Group A merged) ships as its own worktree, one commit, on a branch named after the slice (`hotfix-M9.A4-pat-prefix-leak`). Don't reopen Group A's worktree.
3. **Spec-only slices.** Slices that touch only `development/*.md` (rare; most spec lives in the same PR as code) can ship in a dedicated `docs-*` worktree to keep them off the code review's critical path.
4. **Sequential dependency inside a group.** When slice N+1 *cannot start* until N has merged (rare; usually internal-group slices can chain on disk in one worktree), use two consecutive worktrees off the same branch. Document the chain in the second worktree's first commit message.

**Anti-patterns explicitly forbidden:**

- **Squash-merging a group.** The slice boundary is the whole point. Always `--no-ff`, never `--squash`.
- **Mixing slices from two groups in one worktree.** Even if both touch the same file, the independence story collapses. If two groups genuinely need to land together, that's a sign the group boundary was drawn wrong — re-decompose first.
- **Skipping the slice-level DoD between commits inside a group.** The temptation to "just keep going, I'll run tests at the end" defeats bisectability. If commit N is broken and commit N+1 is broken differently, the bisect bridge is gone.
- **Long-running group worktrees.** If a group worktree is open more than ~3 days, the rebase debt with main starts to matter. Either ship what's there as a partial group (rename the merge message to reflect which slices landed) or pause and rebase before continuing.

**Pre-public posture interaction.** Because there's no Alembic, schema-shape commits inside a group can freely add/drop columns across slices — the next `eyenet init` is the source of truth, not a migration chain. This is what makes M9.C1 → M9.C2 → M9.C3 work as three commits in one worktree without ceremony: each commit's `rm data/*.db && eyenet init` is valid.

---

### Worktree execution matrix

For any operator picking up work, the safe parallelization is determined by `Files touched:` sets. Two milestones with disjoint sets can be executed in two worktrees concurrently. Concrete examples:

| Worktree pair                | Reason it's safe                                                                 |
|------------------------------|----------------------------------------------------------------------------------|
| M9.A1 ‖ M9.B1                | `auth.db` table additions vs `audit.db` table additions — different files        |
| M9.C1 ‖ M9.A2                | `source_domain.py` storage vs `api/v1/auth.py` — different layers                |
| M9.C3 ‖ M9.F1                | `models/collector.py` vs `api/v1/actors.py` — fully disjoint                     |
| M9.E1 ‖ M9.E2                | `sensor/primitives/url_extraction.py` vs `…/channel_reference_extraction.py`    |
| M9.D1 ‖ M9.D2                | `api/v1/sources.py` vs `api/v1/collectors.py` — different router modules         |
| M9.F2 ‖ M9.F3                | `api/v1/linkages_read.py` vs `api/v1/graph.py` — different router modules        |
| M9.G3 ‖ M9.G4 ‖ M9.G5        | three write modules, three worktrees — only `schemas/writes.py` is shared (small merge)|

The reverse pairings — milestones that *cannot* parallelize — are those sharing a `Files touched:` entry. `tests/contract/api/expected_routes.json` is the highest-collision file; any milestone that adds a route updates it, so two route-adding milestones serialize on that one file. Resolve with a small post-merge regeneration.

---

## 17. What we are NOT doing in v1

- Sister-service-to-sister-service HTTP. Bus stays bus.
- Public anonymous endpoints.
- mTLS.
- HTTP/1.1 anywhere in the stack (forbidden, not just deprecated — §12.1.2).
- WebSocket.
- Self-service password reset.
- Per-tenant data isolation (multi-user yes, multi-tenant no — see PLAN.md §810).
- GraphQL. Don't ask.
- Webhooks out (push notifications to integrators). SSE is the streaming surface; webhooks revisit later if a real consumer needs them.
- **Database migration tooling.** EYENET is pre-public; there are no deployed operators. Schema changes during M9 are made by `rm data/*.db && eyenet init`. Alembic, `operations/migrations/`, and `operations/upgrading/POLICY.md` land at v0.1.0 (first public release), not before. The six invariants from §5.5 / §11.5 are still applied as **design constraints** so the eventual Alembic baseline is clean — they shape schemas now without requiring tooling to enforce them.
- **Per-user labels on Prometheus metrics.** Cardinality discipline (§11.7.3). Per-user analytics live in OTLP push, not in the Prometheus scrape. This is enforced by a contract test (§14.4) and is non-negotiable regardless of customer ask.

---

## 18. Done = ?

The API is "done" (M9.6 complete) when:

1. The operator UI can be built against `/v1/openapi.json` without a single endpoint that requires special-case client logic.
2. Every endpoint that returns evidence has a corresponding audit row, verifiable via `/v1/audit/verify`.
3. The hash chain produced by a session with mixed CLI + API operations is a single linear chain — no fork, no gap.
4. `eyenet/query_api/` is deleted.
5. Coverage ≥ 0.89, mypy strict clean, ruff clean, contract test snapshot stable across non-breaking changes.
