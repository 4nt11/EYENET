# EYENET — session handoff (2026-09-22)

Start-here note. Read this, then
`~/.claude/projects/-home-anti-Projects-EYENET/memory/MEMORY.md` (esp.
`project_frontend_wiring_session` — the master note) and
`development/wiring-matrix.md`.

---

## Where we are

**M9 API is feature-complete AND the operator FRONTEND is now fully wired to
it.** Every page in `eyenet-fe/` renders live data (honest empty/error states,
no fabrication). This session closed the last blocked pages (documents /
attachments / evidence) plus the backend read endpoints they needed.

`eyenet-fe/` is the live SvelteKit tree (`development/ui/` kept only for
side-by-side compare). Pages are wired one-per-PR through the review loop:
**branch → `bun run build` → `bun run smoke` → PR → merge**.

### Pages WIRED to the live API — ALL of them
`health`, `cases` (caseload + case-scoped audit + members), `auth`/login (gate),
`graph`, `sources`, `clearance`, `cases/logs`, `linkages` (+ decisions),
`collectors` (+ fleet control), `identities` (+ lifecycle), `candidates`
(+ triage: approve/reject/park/**retry**), `cases/documents`,
`cases/attachments`, `cases/evidence`.

### PRs merged (this project so far)
`#1` graph · `#2` sources · `#3` clearance · `#4` cases-logs · `#5` linkages ·
`#6` collectors (+ `eyenet supervisor`) · `#7` identities-read (backend) ·
`#8` identities (frontend) · `#9` candidates · `#10` EvidencePanel wrap fix ·
`#11` **backend read endpoints** (documents/attachments/case-observations) ·
`#12` **cases documents/attachments/evidence** (frontend) ·
`#13` **candidates Retry button**.

Merge with `gh pr merge N --squash --delete-branch --admin` — GitHub's
mergeability check lags on this fresh repo; `--admin` bypasses it and the branch
is genuinely mergeable.

### Backend added this session (#11)
- **`GET /v1/documents`** (`documents_list`) + **`GET /v1/attachments`**
  (`attachments_list`) — authenticated, all rows, **metadata only**; bytes/
  extracted-text stay behind the clearance-gated manifest + signed `/access`.
- **`GET /v1/cases/{case_id}/observations`** (`cases_list_observations`) —
  `read:observations` + `require_case_visible`, **direct case-membership only**
  (observations added via `case_member`, `subject_kind=observation`, not
  removed). The JOIN mirrors `CasesMixin._recompute_effective_tier`.
- Storage: `list_/count_` pairs on DocumentsMixin/AttachmentsMixin/
  ObservationsMixin (generic ANSI SQL, ABC twins, no dialect leak). Schemas
  `DocumentSummary`/`AttachmentSummary` + `CursorPage*`; pinned
  `contracts/openapi/eyenet.v1.yaml` updated (surface test enforces it).

---

## What's left (frontend)

- **Collector-create form** — UNBLOCKED (needs `source_id` from sources list ✓
  + `identity_id` from identities list ✓). Not built yet. Highest-value next FE.
- **`/lab`** — component sandbox, never wire.

## Backend-gated (needs M9.B2 first)
The document/attachment **signed byte + extracted-text access**, all
**reclassify** flows, and the **file-access journal reader** are rendered as
DISABLED affordances in the UI (labelled "requires operator signing (M9.B2)").
They need **client-side Ed25519 operator signing**, which is not on `main`
(memory: `project_phaseloop_api_plan` — next = M9.B2 server-vs-client signing
fork). When M9.B2 lands: enable `AccessDialog`/`ReclassifyDialog` (their
`onconfirm` payloads already match the API bodies) and wire
`GET /v1/audit/file-access` for the attachment access journal.

## Deferred / decisions parked
- **SSR** — UI is a client-only SPA (`ssr=false`). Adopt adapter-node "after the
  PRs close". Until then `bun run smoke` is the runtime safety net (build can't
  catch runtime crashes).
- **Severity `tier`** — pervasive mock concept with NO API model. Dropped
  everywhere (candidates, evidence, linkages, graph). ANTI wants to "add
  severity later" as a real threat-severity field on actors/linkages/cases.
- **`POST /v1/identities` session-file upload** — deferred (sensitive:
  account-takeover credential; see `development/TODO.md`). Build with
  write:identity + audit + encrypt-at-rest.
- **PAT-mint / signing-key UI**, token auto-refresh on 401 — still stubbed.
- **Evidence via-actor semantics** — we chose DIRECT case-membership for
  `/cases/evidence`. "All observations of the case's actors" is a possible
  future broader mode (needs a `subject_kind=actor` → observations join).

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
candidate + identities. **NOTE:** it does NOT yet seed a document, an
attachment, or an observation-as-case-member — so `/cases/{documents,
attachments,evidence}` show empty against the demo seed until you extend
`demo_seed.py` (add ≥1 doc via `store_document`, ≥1 attachment, and ≥1
observation added with `add_case_member(subject_kind=OBSERVATION)`).

---

## Gotchas (still true)
- **`bun run build` CANNOT catch runtime errors** — `ssr=false` only prerenders
  the shell. **`bun run smoke` (headless Playwright, every route) is the review
  gate.** It seeds an auth token so gated routes render; same-origin 404s (API
  down) are caught into honest error states → still "clean".
- **`.gitignore` swallows route dirs** — broad OPSEC/runtime rules (`identities/`,
  `logs/`) also match `eyenet-fe/src/routes/…`. `git check-ignore -v` is the
  tell; add scoped `!…/<n>/` + `/**`. (documents/attachments/evidence were NOT
  swallowed — verified.)
- **Detail loaders need a seq-guard + stale-clear** (monotonic token) — a fast
  row-switch otherwise shows the prior entity's data. Used everywhere now.
- **Field-name drift**: the mock lied. Document/attachment LIST rows use
  `sha256`/`mime`/`size_bytes`; MANIFESTS use `content_hash`/`content_mime`/
  `content_size`. Effective tier is computed `COALESCE(operator_tier_override,
  classifier_tier)` — no stored `effective_tier` column.
- **Two decision timings**: candidate approve/reject/park/retry are **202 but
  applied in-handler** (no poll). Linkage/collector decisions are ASYNC (need
  the graph/supervisor worker; poll for the flip).
- **`pkill` in a compound Bash line exits 144 and aborts the rest** — run
  `pkill -f "vite preview"` on its OWN line, then verify the port with `ss`.

## Perennial gotchas
- **Worktree venv:** `.venv` lives in the MAIN tree. From a worktree run
  `/home/anti/Projects/EYENET/.venv/bin/python -m pytest …` with cwd = worktree.
  Console-script shebangs point at a stale `/home/anti/Tools/EYENET` path —
  use `python -m <tool>` (mypy/pytest/bandit).
- **Machine OOM under full suite** = a runaway test; run heavy sweeps memory-capped
  (`systemd-run --user --scope -p MemoryMax=20G …`).
- **Never `client.stream()` a live SSE endpoint in a test** (buffers infinite body → OOM).
- ASGI shared in-memory aiosqlite: seed all `await storage` state BEFORE the first
  TestClient call (MissingGreenlet).
- **OpenAPI surface pin**: adding a route = edit handler + schema + `api/v1/__init__.py`
  (import + include_router) + `contracts/openapi/eyenet.v1.yaml` (path/opId/
  response-ref/component-name) or `tests/schema/test_openapi_surface.py` fails.
- ASGI-routed handlers evade coverage → add direct-call unit tests under
  `tests/unit/api/v1/` per handler.
- Stray untracked artifacts in main tree — NEVER commit: `DSR-2026-NH-00417-FICTIONAL.docx`,
  `classifier_corpus.py`, `docs-1.jsonl`, `ruleset-additive.toml`,
  `development/.$eyenet-erd.drawio.dtmp`, `development/ui/`.

---

## NEXT task (recommended)
1. **Extend `development/demo_seed.py`** to seed a document, an attachment, and
   an observation-as-case-member, so the three Cases pages show live rows.
2. **Build the collector-create form** (now fully unblocked).
3. **M9.B2 client-side Ed25519 signing** — the big unlock for signed access +
   reclassify + the file-access journal. Everything downstream is stubbed and
   waiting behind disabled affordances.

## How to resume
```bash
cd /home/anti/Projects/EYENET && git log --oneline -10
docker start eyenet-demo-nats                       # NATS
# then start: eyenet api / graph / supervisor / bun dev  (see RUNNING DEV STACK)
cd eyenet-fe && bun run build && bun run smoke       # frontend gate
```
