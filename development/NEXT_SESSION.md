# EYENET — session handoff (2026-09-22, late)

Start-here note. Read this, then
`~/.claude/projects/-home-anti-Projects-EYENET/memory/MEMORY.md`.

---

## HEADLINE CORRECTION — the API is NOT feature-complete

Earlier handoffs claimed "M9 API is feature-complete." **False.** There are
still **5 live `501 NotImplementedError` skeleton handlers** from M9.0. They
compile, they're in the OpenAPI spec, the frontend calls them — and they return
`501 {"detail":"... (M9.0 skeleton)"}`. The cross-reference "wired" scan missed
them because it checked frontend→endpoint calls, not whether the handler body
was real.

### The 5 unfinished endpoints (grep: `raise NotImplementedError` in `eyenet/api/`)
| Endpoint | Handler file | Storage exists? |
|----------|-------------|-----------------|
| `GET /v1/clearance/grants` (list) | `clearance/api_list_grants.py` | ✗ needs `list_clearance_grants` + `count_` (filters: user_id, scope, active_only) |
| `GET /v1/clearance/grants/{id}` | `clearance/api_get_grant.py` | ✗ needs `get_clearance_grant(grant_id)` |
| `POST /v1/clearance/grants` (grant) | `clearance/api_grant_clearance.py` | ✓ `storage.grant_clearance(...)` exists — wire handler + audit |
| `POST /v1/clearance/grants/{id}/revoke` | `clearance/api_revoke_grant.py` | ✓ `storage.revoke_clearance(...)` exists — wire handler + audit |
| `GET /v1/audit/anchors` | `audit/api_list_anchors.py` | ? check for an anchor-store method; may need one (external-witness anchoring, `project_file_access_journal`) |

Notes for whoever finishes these:
- Schemas already exist: `ClearanceGrantSummary` + `CursorPageClearanceGrantSummary`
  (`api/v1/schemas/clearance.py`). No OpenAPI change needed — the paths/opIds are
  already pinned; just replace the `raise` with a real body.
- The clearance handlers use **raw `Query()` params, not the shared
  `cursor_params` dep** — and `include_total`/`active_only` are **int 0/1**, not
  bool. (That mismatch already bit the FE, see below.)
- Storage read methods = the #11 recipe: `list_/count_` on a ClearanceMixin,
  ABC twins in `repository.py`, generic ANSI SQL. Add direct-call handler unit
  tests under `tests/unit/api/v1/clearance/` (+ `__init__.py` — package dir!).
- `/v1/audit/anchors` is currently swallowed gracefully by the cases/logs page
  (it tolerates the 501), so it's low-urgency vs clearance.

---

## What THIS session actually shipped (merged to main)

- **Control page** wired (`#14`): panic → `POST /v1/panic`; control history read
  from the hash-chained audit log (`GET /v1/audit?subject=eyenet.control.panic`).
- **Backend** (`#15`): `GET /v1/actors` (`actors_list`), `GET /v1/personas`
  (`personas_list`), `GET /v1/calibration`; `ObservationSummary` now carries the
  full typed value (namespace/version + hash/enum/array) for the BEHAVE readout;
  actor **alias** join + real `alias_count`; **`write:actors` operator assessment**
  (`PUT /v1/actors/{id}/assessment`, new scope in admin+analyst baselines);
  **verifier-result persistence** — new `LinkageVerifierResultTable`, recorded for
  every scored pair, surfaced on `LinkageDetail.verifier`.
- **Frontend** (`#18`): actors page (list + dossier + real BEHAVE panel + aliases
  + editable assessment + graph→actor click-through) and personas page (list +
  detail with resolved member handles + Merge/Split dialogs, async-poll).
- **`#17`**: `demo_seed.py` now seeds a document + attachment + observation-as-
  case-member; collector-create form.
- Direct-to-main small fixes: persona member rows link to `/actors?id=<uuid>`
  (`5c83f00`); clearance load sent `include_total=true` → `1` (`598f2b4`) — the
  API contract is int 0/1 everywhere (but the endpoint is still 501, see above).

Dropped, not faked (no backend): threat tier/severity (parked), actor
groups/role_signal/recipe, persona tier/summary.

---

## What's left — the real backlog

### A. Finish the 5 stub APIs (above) — clearance is the visible one
Clearance page currently shows "grants unavailable" because the endpoint 501s.
This is the highest-value backend gap and mostly not complex (2 handlers already
have storage; 2 need read methods; anchors needs a storage check).

### B. Auth surface — only 4 of 14 endpoints wired
Wired: login, login/verify, logout, me. **Not wired:**
- **PAT tokens** — `GET/POST/DELETE /v1/auth/tokens`. Simple CRUD; needs a
  token-management UI (an account/settings page). Check the handlers aren't also
  501 before building the FE.
- **MFA self-enroll** — `POST /v1/auth/mfa/enroll` + `verify-enroll` + `DELETE`.
  Moderate (secret/QR + verify code).
- **token refresh** — `POST /v1/auth/refresh` (auto-refresh on 401; client
  plumbing, no page).
- **stream-token** — `POST /v1/auth/stream-token` (mints the SSE JWT; needed for C).
- **signing-key** — `POST /v1/auth/signing-key/challenge` + `/signing-key`. This
  is the **M9.B2 keystone** (client-side Ed25519). NOT simple. Unlocks: reclassify
  signed bodies, signed document/attachment byte access, and the file-access
  journal reader.

### C. SSE live streams — 0 of 5 wired
`/v1/stream/{linkages,personas,audit,control,all}`. No EventSource in the FE yet
(there's a `stream` nav slug, unbuilt). Needs `stream-token` (B) first. Moderate.

### D. Backend-gated on M9.B2 (signing)
`/v1/audit/file-access` + `/by-user` journal reader; reclassify signed flows;
signed byte access. All rendered as DISABLED affordances in the UI today.

### E. Deferred / parked
- `POST /v1/identities` session-file upload (sensitive credential; write:identity
  + audit + encrypt-at-rest).
- Severity/threat-tier as a real field on actors/linkages/cases.
- SSR (UI is `ssr=false` SPA; `bun run smoke` is the runtime gate).

> Everything else in the operator UI IS wired and working: actors, personas,
> control, cases (+docs/attachments/evidence), collectors (+create), identities
> (+lifecycle), candidates, linkages, sources, graph, health.

---

## RUNNING DEV STACK (all currently UP as of this handoff)
Run every long-lived service **UNSANDBOXED** and **with an explicit `--host`**
(both bit us hard — see memory `feedback_eyenet_api_needs_explicit_host`).

- **NATS** — `docker start eyenet-demo-nats` → `:4223`.
- **API** `:8443`:
  `EYENET_API_CORS_ORIGINS='http://localhost:4173,http://localhost:5173,http://localhost:5180' EYENET_API_METRICS_ENABLED=1 eyenet api --data-dir data --nats-url nats://127.0.0.1:4223 --host 127.0.0.1 --port 8443 --certfile data/dev-tls/cert.pem --keyfile data/dev-tls/key.pem`
  — **omitting `--host` → EADDRINUSE on a genuinely-free port.**
- `eyenet graph --data-dir data --nats-url nats://127.0.0.1:4223`
- `eyenet supervisor --data-dir data --nats-url nats://127.0.0.1:4223 --tick 3`
- **dev**: `cd eyenet-fe && VITE_EYENET_API='https://localhost:8443' bun run dev --port 5180`

**Creds:** admin **`anti`** / `nNj3E&Izar=jeyFHjk=KC-5y`. Accept the self-signed
cert once at `https://localhost:8443/v1/healthz`, then open
`http://localhost:5180`.

**Schema note:** the running `data/*.db` was patched additively this session
(added `actor.operator_assessment` column via ALTER; `linkage_verifier_result`
auto-created on API boot). Pre-public = no migrations, so a fresh `rm data/*.db`
+ reboot + `demo_seed.py` gives a clean current schema (regenerates the admin
password unless you set it).

**Demo data:** `.venv/bin/python development/demo_seed.py --data-dir data`
(API stopped). Now seeds source/actors/messages + collector + linkage +
case+members + candidate + identities + **document + attachment +
observation-as-case-member**.

---

## Workflow (this operator's preference)
- **Cosmetic / simple change → commit straight to `main` + push.** No branch/PR.
- **Big change (endpoints, schema, features) → branch + PR.**
- Self-merge (`gh pr merge --admin`) works only after the operator authorizes it
  in-conversation, and only **one PR per Bash call** (batched merges get denied).
- **Stacked-PR trap:** merging a base branch with `--delete-branch` auto-CLOSES
  any PR based on it. Merge base → let main update → branch the next off main.
- No `Co-Authored-By Claude` trailer.

## Gotchas (still true)
- `bun run build` can't catch runtime errors (`ssr=false`); `bun run smoke`
  (headless Playwright, every route) is the gate. Start `bun run preview --port
  5173` first, `EYENET_SMOKE_URL=http://localhost:5173 node smoke.mjs`, then
  `pkill -f "vite preview"` **on its own line** (exit 144 aborts a compound line).
- New route = handler + schema + `api/v1/__init__.py` (import + include_router,
  list route before `/{id}`) + `contracts/openapi/eyenet.v1.yaml` +
  keep `tests/schema/test_openapi_surface.py` passing (it compares path×method,
  opId set, success `$ref`, component-name set). New enum referenced by a schema
  becomes a generated component → add it to the YAML too.
- **New SQLModel table → also add its `__tablename__` to `_MAIN_TABLES` in
  `sqlite_repo/database.py`** or every query 500s "no such table" (create_all
  uses an explicit table list, not full metadata).
- New test dir under `tests/unit/api/v1/` needs an `__init__.py` (pytest module
  basename collisions otherwise — e.g. two `test_list_handler.py`).
- Run pytest as `.venv/bin/python -m pytest ... -p no:randomly --no-cov` for
  partial runs; memory-cap heavy sweeps (`systemd-run --user --scope -p
  MemoryMax=20G`).
- `include_total` / `active_only` query params are **int 0/1**, not bool.
- Stray untracked artifacts — NEVER commit: `DSR-2026-NH-00417-FICTIONAL.docx`,
  `classifier_corpus.py`, `docs-1.jsonl`, `ruleset-additive.toml`,
  `development/.$eyenet-erd.drawio.dtmp`, `development/ui/`, `development/design system/`.

---

## NEXT task (recommended order)
1. **Finish the clearance API** (4 handlers): wire grant/revoke (storage exists),
   add `list_/get_/count_clearance_grants` storage + wire list/get. Then the
   clearance page works end-to-end. Check `/v1/audit/anchors` storage while there.
2. **PAT token management** (`/v1/auth/tokens` CRUD) — verify handlers are real,
   then build the account/tokens UI.
3. **M9.B2 client-side Ed25519 signing** — the keystone unlocking reclassify +
   signed byte access + file-access journal + (via stream-token) the SSE feeds.

## How to resume
```bash
cd /home/anti/Projects/EYENET && git log --oneline -8
grep -rn "raise NotImplementedError" eyenet/api/   # the live stub list
docker start eyenet-demo-nats
# start api/graph/supervisor/dev UNSANDBOXED + API with --host 127.0.0.1 (see stack)
```
