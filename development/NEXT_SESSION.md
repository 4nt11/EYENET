# EYENET — session handoff (2026-09-21)

Start-here note. Read this, then
`~/.claude/projects/-home-anti-Projects-EYENET/memory/MEMORY.md` and
`development/API_PLAN.md`.

---

## Where we are

**M9 is feature-complete except the frontend.** The HTTP API now has a full
read + write + stream surface plus observability. Recent merges on `main`:

- **Group G — write surface** — `6be368b`
- **Group H — SSE stream surface** — `25fe22c` (rescued from an OOM'd worktree)
- **M9.6 — observability** (metrics, trace SLI, alerts, Grafana) — `baaf135`

Current `main` HEAD: `baaf135`.

Gate at last merge: ruff format+check / mypy --strict (442 files) / bandit /
deptry / detect-secrets all clean. `unit or contract` = **89.30%** cov
(`.coverage-baseline` 0.8906, no-drop satisfied — baseline NOT bumped).
`integration` = **184 passed / 16 skipped / 0 failed** (16 skips = the
`eyenet-extract` venv classifier tests). Run memory-capped (see gotchas).

### What M9.6 shipped
- `eyenet/telemetry/metrics.py` — OTel MeterProvider, dual exposition (Prometheus
  scrape `EYENET_API_METRICS_ENABLED` + OTLP push `EYENET_OTEL_ENDPOINT`), the
  §11.7.2 instrument catalog, per-instrument cardinality View allow-lists (§11.7.3).
- Real `GET /v1/metrics` (was a 501 stub): `read:metrics` scope + enabled-gate,
  404 when off. Recording wired at request/auth/audit/SSE/idempotency chokepoints
  + boot-time health gauges.
- trace→REQUIRED cutover is **count-only** (never drop evidence):
  `eyenet_api_trace_propagation_missing_total` SLI + canonical `ZERO_TRACEPARENT`.
- `operations/` — Prometheus alert rules, Grafana dashboard, tail-sampling
  collector config, least-privilege PAT scrape recipe.
- Details + gotchas: `[[project_m9_6_done]]`, `[[feedback_otel_global_provider_testing]]`.

---

## What's left to do (general)

### The big track
- **Frontend — not started.** The operator UI. The API is ready for it: complete
  read/write/stream surface, stream tokens + EventSource fallback, OpenAPI at
  `/v1/openapi.json` (TS codegen target, §12.5). This is the main remaining M9 work.

### Loose ends carried in code (small → medium)
- **`/healthz` + `/readyz` are still M9.0 501 stubs.** Because of this the M9.6
  health gauges (`eyenet_api_healthy`, `eyenet_api_ready{component}`,
  `storage_open`, `bus_connected`) are **boot-time only** — no dynamic re-check.
  Implementing the two probe handlers makes the gauges live.
- **Trace hard-error cutover** deferred until the trace-missing SLI is proven zero
  in the field (currently count-only per operator decision).
- **Collector-side `_zero_traceparent` consolidation** — telegram/matrix real+stub
  still keep local copies; API+telemetry use the canonical `propagation.ZERO_TRACEPARENT`.
- **QR_CODE join dispatch** — needs decode-at-discovery to populate a usable t.me
  link before `select_join_action` can add QR_CODE (E5.5 was invite-link-only).
- **`_KIND_PREFERENCE` ↔ `select_join_action` coupling** — supervisor + collector
  supported-kind sets must grow in lockstep; a shared source is cleaner at platform #3.
- **Live ban-on-the-wire → `joined→parked`** — 403s on an already-joined group
  should close membership; `quarantine_on_ban` only covers the join path.
- **`joining`/`requested` redelivery rescan** — a supervisor crash between the
  transition and the publish strands a candidate; a rescan is the fix.
- **Storage `repository.py` ABC refactor** — ~1700-line flat ABC; split into
  per-domain fragments (keep the flat call surface). Own worktree, not blocking.
  See `[[project_refactor_fat_storage_repository]]`.

### Done since the old handoff (do not re-chase)
- `REQUESTED → JOINED` resolution detector — **DONE** (`546e710`): event-driven
  (`_maybe_confirm_requested`) + periodic probe (`_probe_requested_memberships`)
  → `confirm_requested_membership`, per-collector scoped.
- Group G write surface, Group H SSE, M9.6 observability — all merged (above).

---

## NEXT task (recommended)

**Implement the real `/healthz` + `/readyz` handlers** (`eyenet/api/v1/health/
api_healthz.py`, `api_readyz.py` — currently 501 stubs). Small, self-contained,
and it lights up the M9.6 health gauges with live signal:
- `/healthz` — liveness: process up → 200.
- `/readyz` — per-component readiness (storage open, bus connected, jwt keys
  loaded); reuse `app.state` deps; call `metrics.set_health(...)` so the gauges
  reflect live probes instead of boot-time optimism.

Then the big one: **start the frontend** (separate repo per §12.5; generate the TS
client from `/v1/openapi.json`).

---

## Environment gotchas
- **Machine OOM under the full suite** = a hung/ballooning test, not ambient
  pressure. Run heavy sweeps memory-capped so a runaway is scoped, not fatal:
  `systemd-run --user --scope -p MemoryMax=20G -p MemorySwapMax=0 -- <pytest>`.
- **Never `client.stream()` a live SSE endpoint in a test** — the sync starlette
  TestClient buffers the whole infinite body → hang + OOM. Prove SSE at the
  handler/generator unit level. See `[[feedback_sync_testclient_infinite_sse_oom]]`.
- **OTel global provider is set-once** — test Views on a local MeterProvider; spy
  on module instruments where bound. See `[[feedback_otel_global_provider_testing]]`.
- **Worktree venv:** the `.venv` lives in the MAIN tree
  (`/home/anti/Projects/EYENET/.venv`). From a worktree run
  `/home/anti/Projects/EYENET/.venv/bin/python -m pytest …` with **cwd = the
  worktree**. Never the bare `.venv/bin/pytest`. NOTE: the venv console-script
  shebangs point at a stale `/home/anti/Tools/EYENET/.venv` path — `bandit`/`deptry`
  etc. must be run as `python -m bandit` / `python -m deptry`. A `uv sync` /
  venv recreate fixes it.
- **Worktree edit trap:** in a worktree, Edit/Read with a MAIN-tree path silently
  edits the wrong tree. Always use the worktree absolute path.
- ASGI / shared in-memory aiosqlite: seed all `await storage` state BEFORE the
  first TestClient call (MissingGreenlet).
- §3.3 flakes: `test_impostor_pool_loader`, `test_service_branches`,
  `test_stylometric_kernel_memo` jitter under random order — confirm under
  `-p no:randomly` + in isolation before treating as a regression.
- Stray untracked artifacts in the main tree — NEVER commit:
  `DSR-2026-NH-00417-FICTIONAL.docx`, `classifier_corpus.py`, `docs-1.jsonl`,
  `ruleset-additive.toml`, `development/.$eyenet-erd.drawio.dtmp`.
- Worktrees left on disk (both merged, safe to reap): `phaseH-sse`,
  `phase-m9.6-observability` — `git worktree remove` + `git branch -d`.

---

## How to resume

```bash
cd /home/anti/Projects/EYENET
git log --oneline -8
.venv/bin/python -m pytest -m "unit or contract" -q --no-cov         # fast inner loop
# full battery, memory-capped (heavy: spaCy/nsjail):
systemd-run --user --scope -p MemoryMax=20G -p MemorySwapMax=0 -- \
  .venv/bin/python -m pytest -m "unit or contract or integration" -q
```

Deep refactor / new milestone → worktree branch + atomic `--no-ff` merge
(CLAUDE.md §6). Heed the worktree traps above.
