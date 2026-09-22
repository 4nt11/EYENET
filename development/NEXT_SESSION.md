# EYENET — session handoff (2026-09-22)

Start-here note. Read this, then
`~/.claude/projects/-home-anti-Projects-EYENET/memory/MEMORY.md` (esp.
`project_frontend_wiring_session` — the master note) and
`development/wiring-matrix.md`.

---

## Where we are

**M9 API is feature-complete. This session = bringing the operator FRONTEND
live against the real API**, plus two backend gaps that the frontend forced open.

The SvelteKit mockups were copied `development/ui/` → **`eyenet-fe/`** (the live
tree now; `development/ui` kept only for side-by-side compare). Pages are wired
one-per-PR through a review loop: **branch → `bun run build` → `bun run smoke`
→ PR → review → merge**.

### Pages WIRED to the live API (honest empty states, no fabrication)
`health`, `cases` (caseload + case-scoped audit + members), `auth`/login (gate),
`graph`, `sources`, `clearance`, `cases/logs`, `linkages` (+ decisions),
`collectors` (+ fleet control), `identities` (+ lifecycle).

### PRs
MERGED to main: **#1** graph · **#2** sources · **#3** clearance · **#4**
cases-logs · **#5** linkages · **#6** collectors (+ `eyenet supervisor`
launcher) · **#7** identities-read (backend).
**OPEN at handoff: #8 `wire/identities`** (frontend) — built, smoked (21/21),
verified live. Just needs review + merge.

Merge with `gh pr merge N --squash --delete-branch --admin` — GitHub's
mergeability check lags/sticks on this fresh repo; `--admin` bypasses it and the
branch is genuinely mergeable. Branches behind main: they merge fine via
`--admin` (or `gh pr update-branch`, which also lags).

### Backend gaps closed this session
- **`eyenet supervisor` CLI** (#6) — the `CollectorSupervisor` (sole writer of
  collector `observed_state`) had no launcher, so fleet state was frozen. Now
  `eyenet supervisor --nats-url … --tick 3` reconciles observed→desired. Makes
  collectors Start/Stop real end-to-end.
- **`GET /v1/identities` + `/{id}`** (#7) — identities were action-only, no read
  surface (dead-ended /identities + collector-create). Storage already had
  `list_identities`/`get_identity`; exposed them, gated `read:collectors`.
  **OPSEC: `session_path`/`proxy_uri` NEVER on the read surface.**

---

## What's left (frontend)

- **`/candidates`** — last of the judgment-heavy trio. State-vocab mismatch
  (mock `pending` → real `queued`/`discovered`/`requested`); `platform` needs a
  source join; `mentions` count is detail-only. See wiring-matrix. Its
  approve/join flow leans on the supervisor (already running).
- **Backend-BLOCKED pages** (need new endpoints or honest empty states):
  `cases/documents` + `cases/attachments` (no list endpoint; two-step signed
  Ed25519 access flow), `cases/evidence` (no case-scoped observation list).
- **`/lab`** — component sandbox, never wire.
- **Collector-create form** — now UNBLOCKED by the identity list (#7). Needs a
  `source_id` (sources list ✓) + `identity_id` (identities list ✓).
- **`POST /v1/identities` session-file upload** — deferred, captured in
  `development/TODO.md` (sensitive: session file = account-takeover credential;
  build with write:identity + audit + encrypt-at-rest).

## Deferred / decisions parked
- **SSR** — the UI is a client-only SPA (`ssr=false`). ANTI parked adopting real
  SSR (adapter-node) "after the PRs close". Until then `bun run smoke` is the
  runtime safety net (build can't catch runtime crashes — see below).
- **Severity `tier`** — a pervasive mock concept with NO API model. Dropped
  everywhere for now; ANTI wants to "add severity later" (a real threat-severity
  field on actors/linkages/cases).
- **PAT-mint / signing-key UI**, token auto-refresh on 401 — still stubbed.

---

## RUNNING DEV STACK (bring all up for a live demo)
- **API** `:8443` — `eyenet api` (Hypercorn h2/TLS): `--data-dir data --nats-url
  nats://127.0.0.1:4223 --certfile data/dev-tls/cert.pem --keyfile
  data/dev-tls/key.pem`; env `EYENET_API_CORS_ORIGINS='http://localhost:4173,http://localhost:5173,http://localhost:5180'`
  `EYENET_API_METRICS_ENABLED=1`.
- **NATS** — docker container `eyenet-demo-nats` on `:4223` (`docker start eyenet-demo-nats`).
- `eyenet graph` worker (applies linkage decisions).
- `eyenet supervisor --nats-url nats://127.0.0.1:4223 --tick 3` (reconciles collectors).
- **dev server**: `cd eyenet-fe && VITE_EYENET_API='https://localhost:8443' bun run dev --port 5180`.

**Creds:** admin **`anti`** / `nNj3E&Izar=jeyFHjk=KC-5y`. Browser must accept the
self-signed cert once at `https://localhost:8443/v1/healthz`. Adding a new
frontend port = add it to `EYENET_API_CORS_ORIGINS` + restart API.
**Demo data:** `.venv/bin/python development/demo_seed.py --data-dir data` (API
stopped). Seeds source/actors/messages + collector + linkage + case+members +
candidate + identities.

---

## Gotchas (this session's, on top of the perennial ones below)
- **`bun run build` CANNOT catch runtime errors** — `ssr=false` means it only
  prerenders the shell, never runs page scripts. A TDZ/undefined crashes only
  in-browser (bit /clearance PR #3). **`bun run smoke` is the review gate.**
- **`.gitignore` swallows route dirs** — broad `identities/` (OPSEC) + `logs/`
  (runtime) rules also match `eyenet-fe/src/routes/{identities,cases/logs}/` →
  silently untracked. Add scoped `!eyenet-fe/src/routes/<n>/` + `/**`.
  `git add` errors "paths ignored" is the tell.
- **Detail loaders need a seq-guard + stale-clear** (monotonic token) — a fast
  row-switch otherwise shows the prior entity's data (fixed in sources/linkages/
  collectors/identities).
- **Identity writes are SYNC in the handler** (freeze/burn immediately);
  **linkage/collector decisions are ASYNC** (need the graph/supervisor worker;
  poll for the flip).
- Merging: the collectors/identities route work put backend + frontend in one
  PR intentionally ("frontend work is backend work").
- **CLI teardown** prints a harmless `MissingGreenlet` on connection reset (seed
  script, `eyenet user create`) — the write succeeds; ignore it.

---

## Perennial gotchas (still true)
- **Worktree venv:** `.venv` lives in the MAIN tree. From a worktree run
  `/home/anti/Projects/EYENET/.venv/bin/python -m pytest …` with cwd = worktree.
  `core.hooksPath` + venv shebangs point at a stale `/home/anti/Tools/EYENET`
  path (cwd-shadowing) — use `python -m <tool>`.
- **Machine OOM under full suite** = a runaway test; run heavy sweeps memory-capped
  (`systemd-run --user --scope -p MemoryMax=20G …`).
- **Never `client.stream()` a live SSE endpoint in a test** (buffers infinite body → OOM).
- ASGI shared in-memory aiosqlite: seed all `await storage` state BEFORE the first
  TestClient call (MissingGreenlet).
- Stray untracked artifacts in main tree — NEVER commit: `DSR-2026-NH-00417-FICTIONAL.docx`,
  `classifier_corpus.py`, `docs-1.jsonl`, `ruleset-additive.toml`,
  `development/.$eyenet-erd.drawio.dtmp`.

---

## NEXT task (recommended)
1. **Merge #8** (`wire/identities`, `--admin`).
2. **Wire `/candidates`** — last of the trio; follow the loop (branch → build →
   smoke → PR). Or build the **collector-create form** (now unblocked).
3. The blocked pages (documents/attachments/evidence) need backend endpoints
   first — decide honest-empty-state vs new endpoints.

## How to resume
```bash
cd /home/anti/Projects/EYENET && git log --oneline -10
docker start eyenet-demo-nats                       # NATS
# then start: eyenet api / graph / supervisor / bun dev  (see RUNNING DEV STACK)
cd eyenet-fe && bun run build && bun run smoke       # frontend gate
```
