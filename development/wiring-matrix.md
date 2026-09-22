# EYENET frontend → API wiring matrix (Phase 1 discovery)

Result of the read-only discovery pass over `eyenet-fe` mockup pages vs
`contracts/openapi/eyenet.v1.yaml`. Drives Phase 2 batched wiring.

**Already wired:** `/health`, `/cases` (caseload + case-scoped audit + members),
`/auth` (login gate + session).

## Recurring facts (apply everywhere)
- **`tier` severity (critical/high/medium/low) does not exist in the API.** It
  drives rail colors / THREAT_LABEL / tierDot on actors/personas/linkages/graph
  and the evidence table. The only tier is `SensitivityTier` (normal/restricted/
  classified) on cases/documents/attachments/observations. Never conflate them;
  drop severity where there's no field.
- **Friendly ids (SRC-/ACT-/GC-/DOC-…) are all UUIDs server-side.**
- **List schemas omit per-row aggregate counts** (collector groups, candidate
  mentions, actor aliases-as-names) → detail-pane or N+1, never fabricate.
- **No user-directory endpoint:** audit/linkage/clearance rows carry `user_id`
  UUIDs, not handles. Resolve self via `auth.user`; others show short UUID.
- Enums serialize lowercase; all lists are opaque-cursor paginated.

## Per-page

| Page | Primary endpoint(s) | Complexity | Notes |
|---|---|---|---|
| `/sources` | GET /v1/sources, GET /v1/sources/{id} (domains inlined) | moderate | `platform→kind`, `name→display_name`, `domainCount→active_domain_count`. **No** `state`/`lastIngest`/domain add-remove. |
| `/collectors` | GET /v1/collectors, /collectors/health, /{id}, /{id}/memberships | moderate | single `state`→ desired+observed split; `degraded` not an enum; groups-count + identity are detail-only (N+1). |
| `/candidates` | GET /v1/candidates, GET /v1/candidates/{id} | hairy | **state vocab mismatch**: mock `pending`→ real `queued`/`discovered`/`requested`. `platform` needs source join; `mentions` detail-only; strict transitions (409). |
| `/linkages` | GET /v1/linkages, /{id}, POST confirm/reject/suspect | moderate | list+detail+decision all exist. `pair` handles need per-actor fetch; `tier` absent; `decided_by` UUID; evidence.detail is object; decisions 202+Idempotency-Key. |
| `/actors` | GET /v1/actors/{id}(+/observations,/neighbors,/timeline); sidebar via /v1/graph/search?q= | hairy | **no actor list** (search-only). BehavePanel/recipe/role_signal/assessment/aliases-names/tier all unbacked. neighbors nested under `attrs`. |
| `/personas` | GET /v1/personas/{id}, /{id}/members, POST merge/split | hairy | **no persona list/search at all**. tier/summary unbacked. "Attribution basis" = N+1 linkage+actor fetches. |
| `/graph` | GET /v1/graph/stats, GET /v1/graph/search?q= | moderate | topology has NO endpoint (already stubbed in-page). Only 3/6 stat tiles backable (actors/personas/linkages-total; Nodes/Edges/Sources none). search is actors-only, `q` required. |
| `/clearance` | GET /v1/clearance/grants(+/{id}), POST grant/revoke | moderate | cleanest CRUD. `status` derived from active/revoked_at/expires_at; `scope` vocab matches; tier column + usernames unbacked; grant/revoke need admin:clearance. |
| `/identities` | POST claim/release/freeze/burn/freeze_all only | **hairy — blocked** | **NO read endpoint of any kind.** Table + detail cannot populate. Needs a new backend list endpoint before wiring. |
| `/cases/logs` | GET /v1/audit(?subject_id), /audit/verify, /audit/anchors | moderate | all endpoints exist. `tamper` is verify-derived, not per-row; anchor `target` unbacked. Cleanest of the case subpages. |
| `/cases/evidence` | (no clean fit) actors/{id}/observations | hairy | **no case-scoped observation list**; no observation-detail endpoint; severity-vs-sensitivity mismatch. |
| `/cases/documents` | GET /{id}/manifest, POST /{id}/access, /reclassify | hairy — blocked | **no GET /v1/documents list** → table can't self-populate. Two-step signed Ed25519 access. |
| `/cases/attachments` | GET /{id}/manifest, POST /{id}/access, /reclassify, GET /audit/file-access | hairy — blocked | **no GET /v1/attachments list**. Two-step signed access; journal keyed by content-hash. |
| `/control` | POST /v1/panic (202), GET /v1/audit (control), /stream/control | moderate | **real irreversible write**: needs `confirm:I_UNDERSTAND` + reason + Idempotency-Key. posture from system/stream, not the POST. |
| `/lab` | none | clean — leave as-is | pure component sandbox; do NOT wire. |

## Backend gaps worth a decision (block honest wiring)
1. **No list endpoints** for `documents`, `attachments`, `identities` → those
   three tables cannot self-populate. Either add `GET /v1/{documents,attachments}`
   + an identity-pool read endpoint, or ship honest empty/"no endpoint" states.
2. **No case-scoped observation list** for `/cases/evidence`.
3. **No user directory** → UUIDs instead of handles anywhere a user/actor is
   referenced by id (audit, linkage pair, persona members, clearance grants).
4. **Severity tier** is a pervasive mock concept with no model — decide: drop it,
   or add a threat-severity field to actors/linkages/cases.

## Phase 2 batching suggestion
- **Clean/independent first (safe to batch, one agent each):** `/sources`,
  `/graph`, `/clearance`, `/cases/logs`.
- **Do together (judgment-heavy):** `/collectors`, `/candidates`, `/linkages`.
- **Blocked on backend (decide before wiring):** `/identities`, `/cases/documents`,
  `/cases/attachments`, `/cases/evidence`.
- **Leave:** `/lab`.

## Demo data
`development/demo_seed.py` seeds a source/group/actors/messages + collector +
linkage + a visible case (owner-collaborator) with members + a candidate. Run
with the API stopped: `.venv/bin/python development/demo_seed.py --data-dir data`.

## Review loop (MANDATORY before merging a wired page)
`bun run build` only prerenders the fallback shell (`ssr=false`), so it does NOT
execute page `<script>`s — a runtime fault (TDZ, undefined access) compiles
clean and only crashes in a browser. This bit PR #3 (a `statusTone` TDZ that
white-screened `/clearance`, invisible to the build). So every review runs the
headless smoke:

```
bun run dev            # (or any server) then, in another shell:
bun run smoke          # eyenet-fe/smoke.mjs — Playwright, mocks the API + seeds
                       # a token, loads every discovered route, FAILS on any
                       # uncaught pageerror/console error. Exit 1 = a route throws.
```

It auto-discovers routes from `src/routes`, so new pages are covered for free.
`EYENET_SMOKE_URL` overrides the target (default `http://localhost:5173`).
Build-passes is necessary but NOT sufficient — smoke-passes is the gate.
