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
| POST | `/identities/freeze_all` | `write:identity` | `eyenet.identity.freeze_all` |
| POST | `/panic` | `write:panic` | `eyenet.control.panic` (global) |

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
read:restricted    read:classified                                       # §4.7 sensitivity tiers — grant-only, never in baseline
write:linkage_decision  write:identity  write:panic
write:cases                                                            # §4.10 create cases, manage members/metadata on owned cases
stream:linkages    stream:personas     stream:audit    stream:control
admin:users        admin:tokens        admin:clearance                   # admin:clearance is required to grant/revoke §4.8 clearances
admin:reclassify                                                       # §4.9 sensitivity-tier promotion — grant-only, never in baseline
admin:case                                                             # §4.10 archive/reopen, force-collaborator, archived-case access — grant-only
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
| `POST /v1/identities/freeze_all` | 202 | `WriteAccepted` | 409 |
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

### 12.4 CORS

For the operator UI's origin only. Configurable list in `config.toml`. No `*`. `Access-Control-Allow-Credentials: true`. `Access-Control-Expose-Headers: X-Request-Id, X-RateLimit-Remaining`.

### 12.5 OpenAPI

`/v1/openapi.json` and `/v1/docs`. Both require `read:graph` (any authenticated user gets them); no anonymous schema disclosure when `ALLOW_PUBLIC=1`.

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
6. **Idempotency key TTL.** 24h? 7d? Storage cost is low. Provisional: 7d.
7. **JWT key rotation cadence.** Manual via `eyenet api rotate-keys` CLI for v1. Automated rotation deferred.
8. **Scope cache TTL.** §4.4.1 sets 60s. Revisit after first load test: if scope lookup is genuinely free on indexed SQLite reads, drop to 0 (no cache) and remove the carve-out list. Caching exists only to make the design defensible under load; if there's no load problem, it's surface area we don't need.
9. **PAT scope semantics.** PATs today inherit live `system_user_scope` like JWTs do. Alternative: PATs carry a frozen scope subset at mint time (typical OAuth2 PAT pattern), so revoking a user's scope doesn't silently broaden every PAT's effective grant inversely. Provisional: live lookup (matches JWT path), but worth a second think before M9.2.

---

## 16. Milestones

Sized for one-commit-series each, matching the M5–M8 cadence.

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

#### M9.1b — Auth-token storage + JWT

Unblocks `/v1/auth/login`, `/refresh`, `/logout`, `/me`, PAT mint/list/revoke, and the JWT denylist enforcement path.

- **New tables in `messages.db`** (co-located with `system_user`):
  - `system_user_credential` — authoritative `password_hash` + `mfa_secret_encrypted` + `password_updated_at`. STRIPS the inline columns from `SystemUserTable`.
  - `refresh_token` — issued/expires/revoked/replaced_by; rotation chain.
  - `personal_access_token` (§4.4 scope list applies) — name, hash, prefix, scopes, last_used_at, expires_at, revoked_at.
  - `jwt_denylist` — `(jti, expires_at)`; rows purgeable after `expires_at`.
  - `system_user_scope` — additive routine scopes; clearance grants stay in their own audit-DB table from 9.1a.
- Storage typing pass: methods declare concrete return types; all `cast()` removed from current `query_api/routes.py` (prep for the surface rewrite).
- `eyenet/api/auth/jwt.py` — RS256 sign/verify, kid rotation hooks.
- `/v1/auth/login`, `/refresh`, `/logout`, `/me` handlers; `eyenet/api/v1/schemas/auth.py` finalises `LoginRequest`, `TokenPair`, `AccessToken`, `UserMe` (each with §9.5 docstring → `MODELS.md` §2.17).
- `RequireScope` dependency factory + `current_user` resolver wired to consult both `system_user_scope` and the active `system_user_clearance_grant` rows from 9.1a.
- CLI: `eyenet user create`, `eyenet user reset-password`, `eyenet user scopes`.
- `eyenet.audit.auth.{login.success,login.failure,refresh,logout,token.minted,token.revoked}` emission on every auth event.
- **Definition of done:** PAT mint → use → revoke round-trip; refresh-token rotation chain test; jti denylist hit blocks reuse; Schemathesis coverage extends to the four auth endpoints.

#### M9.1c — File-access journal

Unblocks signed byte-serving for `restricted`/`classified` attachments (§5.6–5.9) and the exoneration query.

- **New tables in `audit.db`:**
  - `system_user_signing_pubkey_history` — every historical Ed25519 pubkey; fingerprint = `sha256(verifying_key_DER)[:8]`.
  - `file_access_acknowledgment` (§5.7) — operator's signed pre-read receipt; 60s nonce TTL, single-use; reason ≥16 chars.
  - `file_access_journal` (§5.6) — every byte-served event; mandatory Ed25519 signature over canonical form; fingerprint reference for post-hoc verification. CHECK: tier `normal` may skip grant/acknowledgment fields; `restricted`/`classified` MUST populate both.
- Helpers in `eyenet/storage/file_access.py`: `record_access`, `query_by_user`, `query_by_content_hash`, `verify_signature(row)`. Ed25519 via `cryptography`.
- **Definition of done:** signed-access round-trip; exoneration query returns chronologically-ordered signed rows; tampering with `served_at` invalidates the signature; the §5.9 audit subjects are emitted on every byte-fetch path.

### M9.2 — PATs
- `personal_access_token` table — already created in M9.1b. M9.2 is the handler layer on top.
- `POST /v1/auth/tokens`, `GET /v1/auth/tokens`, `DELETE /v1/auth/tokens/{id}`.
- PAT auth path in the same middleware as JWT (same `current_user` contract).
- `admin:tokens` scope wired up.

### M9.3 — Read surface + audit middleware (parity + replacement)
- All read endpoints under §3.2, §3.3 implemented.
- All read-side schemas land in `eyenet/api/v1/schemas/` per the §9.6 matrix: `actors.py`, `personas.py`, `linkages.py` (summary + detail), `graph.py`, `audit.py`, `pagination.py`. Every schema with a `from_domain` translator and `MODELS.md` reference docstring (§9.5).
- Cursor pagination (`CursorPage[T]`).
- Enum-typed query params.
- `evidence_access` audit middleware emits per-subject before response body is written. Failure → 503.
- Schemathesis stateful mode enabled across the read surface; CI gate.
- `eyenet/query_api/` deleted in the final commit of this series. All callers redirected to `/v1/`.

### M9.4 — Write surface
- All write endpoints under §3.4.
- `eyenet/api/v1/schemas/writes.py` lands with the shared `WriteAccepted` response model and per-action request models (`LinkageDecisionRequest`, `IdentityActionRequest`). Every write endpoint declares `response_model=WriteAccepted` and `status_code=202`.
- `Idempotency-Key` middleware + `idempotency_record` table.
- `linkage_event_log` / `persona_event_log` / `identity_event_log` tables created (§11.5) — every state transition writes one row with `traceparent` for SSE replay.
- Writes follow the §5.5 / §10.3 durability rule: durable audit append (gate) → durable event-log append → async bus publish for both audit and domain events.
- Schemathesis stateful runs include the full write cycle and end every run with `GET /v1/audit/verify`; chain must verify clean as a CI gate.
- CLI parity: `eyenet linkage confirm/reject` continues to work, uses the same audit append + event log path, and emits the same audit shape (no divergence between CLI and API audit format).

### M9.5 — SSE streaming
- `/v1/stream/linkages`, `/personas`, `/audit`, `/control`, `/all`.
- `eyenet/api/v1/schemas/stream.py` lands with the per-event payload models referenced by the `x-eyenet-sse-events` OpenAPI extension (§9.7). TypeScript codegen now produces a typed discriminated-union event handler.
- **Storage-backed replay via `StreamReplaySource`** (§6.2, §6.5). No durable bus consumers; the bus is used only for live tail via `BusClient.subscribe(subject)`. MemoryBus, NATS-core, and JetStream all work identically because durability lives in storage.
- `Last-Event-ID` resume — handler invokes `source.replay(after=...)` until drained, then switches to bus live-tail with overlap dedup by event id.
- Fallback `/v1/auth/stream-token` path for browser EventSource (the polyfill in §6.4.1 is the primary path).
- Heartbeats + per-topic backpressure + `stream.gap` / `stream.backpressure` / `stream.expired` events.
- Custom SSE middleware (§11.4.1) — disable stock FastAPI OTel SSE instrumentation; install the connection-event-log + per-event-delivery-span model.

### M9.6 — Hardening
- Per-token sliding-window rate limit.
- CORS for configured operator-UI origins.
- `X-Forwarded-For` middleware gated by `EYENET_API_TRUST_PROXY_HEADERS=1`.
- TypeScript client codegen pipeline established (artifact only — UI lives elsewhere).
- Load test profile in `tests/load/api/`.
- `/v1/metrics` Prometheus endpoint (§11.7), opt-in via `EYENET_API_METRICS_ENABLED=1`, scope-gated `read:metrics`, with view filters stripping high-cardinality labels for Prom exposition. Health gauges mirroring `/healthz` / `/readyz`. Cardinality contract test in `tests/contract/api/` (§14.4). Example Grafana dashboard checked into `operations/dashboards/` and Prometheus alert rules YAML into `operations/alerts/`.
- Coverage gate raised from 0.845 (M8 floor) to 0.89.

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
