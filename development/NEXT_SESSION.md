# EYENET — session handoff (2026-06-06)

Start-here note. Read this, then
`~/.claude/projects/-home-anti-Tools-EYENET/memory/MEMORY.md` and
`development/API_PLAN.md`.

---

## Where we are

- **M9 Group E — Discovery runtime (E1–E4) + D4 Case-model fold-in — DONE + MERGED to `main`.**
  - Branch `groupE-discovery-runtime`, slice-per-commit, `--no-ff` merge.
  - Slices: storage+D4-Case `2ffe2de`, E1 url_extraction `7f7251c`, E2a channel_ref
    `87547ed`, E2b scoring+DiscoverySensor `8d68e70`, E3 supervisor+eligibility `4b1c869`,
    E4 scout graduation `2826186`, wrap `<slice5>`.
- **This turns the D3 eligibility stub into a real gate.** `GET /v1/candidates/{id}` now
  surfaces real §4.12.3 verdicts (dedup/redundancy + depth + scout availability).
- Battery: full `unit or contract or integration` run = **2004 passed / 16 skipped / 8 failed**.
  The 7–8 (count jitters run-to-run, confirming nondeterministic state pollution) are the
  documented §3.3 log-capture flakes (verifier service-branches, impostor-pool, stylometric
  kernel-memo) — all pass in isolation, NOT regressions (none of those modules were touched).
  Coverage **89.83%** (gate 84%; `.coverage-baseline` left at 0.8906 — no-drop satisfied, not
  ratcheted, to avoid locking the baseline into flaky-run jitter, per the Group D precedent).

## Group E as-built deviations (all documented in code + API_PLAN §Group E)

- **New `eyenet/sensor/discovery/` seam**, NOT `sensor/primitives/`: discovery extractors
  write storage per message with collector/group context (`DiscoveryExtractor` ABC +
  resolved `MessageContext`); the pure stylometric primitive contract was kept clean.
- **`DiscoverySensor`** (`eyenet/sensor/discovery_sensor.py`) resolves `RawMessageEnvelope`
  → `MessageContext`: collector via **`resolve_collector_by_instance_id`** (the 8-char bus
  `instance_id` is a hash, reverse-matched across the fleet — it is NOT stored on
  `CollectorTable`); actor via `resolve_actor_id`; group + lineage via
  `upsert_group`/`group_lineage`.
- **DB `IdentityTable` is the source of truth for the discovery-loop role/state/graduation
  machine.** The file pool (`FileIdentityPool`) stays the credential/session store; the
  **file↔DB provisioning bridge is deferred to E5**. An empty identity table correctly
  yields `NO_SCOUT_AVAILABLE` / no graduations.
- **`SQLAlchemy Enum` persists the enum NAME (uppercase)** — Case-policy CHECK constraints
  use `'PREFER_SINGLE'` etc., matching `ck_candidate_state`/`ck_identity_role`. Lowercase is
  only the JSON wire boundary.
- **Scoring v1 is frozen + deterministic** (distinct mentioning groups·0.3 + actors·0.2,
  capped). Auto-*queue* fires on a Case `auto_join_score_threshold`; auto-*approve* stays
  OFF by default (per-Case opt-in, §4.12.1).
- **`lease_scout`** is atomic find+claim for the single-supervisor case; cross-process
  concurrency needs a `BEGIN IMMEDIATE` override like the audit chain (CLAUDE.md §2.6) —
  deferred while there is one supervisor process.

## What's still open

- **M9.E5 — Telegram collector recursion** (the one deferred E slice): the collector
  consuming `JoinGroupCommand`, the platform join, `joining→joined`,
  FloodWait/InviteExpired mapping. Coverage-omitted live-service code (§3.4). Also closes
  the **file↔DB identity bridge** + the **live scout-burn trigger** (`quarantine_scout` is
  built + tested; nothing calls it yet).
- **D4 HTTP endpoints** (`GET/PUT /v1/cases/{id}/seed-roots`, `POST .../{group_id}`): the
  Case model + storage are done; the endpoints sit on the `/v1/cases` tree whose CRUD
  handlers are still `NotImplementedError` stubs (a Case-API group). Thin follow-on.
- The supervisor's eligibility verdict at dispatch: a structural fail (OVER_DEPTH /
  SKIP_DUAL_COVER / NO_REACHABLE_ROOT) currently leaves the candidate APPROVED and logs
  each tick — no operator-facing surfacing yet (Group H stream / an admin override path).

## Environment gotchas

- **No worktree this milestone** — the worktree's edits landed in the main checkout (paths
  were absolute-main, not worktree-relative), so work moved to branch
  `groupE-discovery-runtime` in the main checkout. Lesson: in a worktree session, use
  worktree-relative paths or `cd` into it.
- **ASGI / shared in-memory aiosqlite:** seed all `await storage` state BEFORE the first
  TestClient call; interleaving raises `MissingGreenlet`. The same StaticPool teardown
  raises a harmless `MissingGreenlet` at interpreter exit in standalone scripts (ignore it).
- Stray untracked artifacts — NEVER commit: `DSR-2026-NH-00417-FICTIONAL.docx`,
  `classifier_corpus.py`, `docs-1.jsonl`, `ruleset-additive.toml`, `development/.$eyenet-erd.drawio.dtmp`.

---

## NEXT: candidates for the follow-up milestone

1. **M9.E5 — Telegram recursion** — closes the discovery loop end-to-end (approve → real
   join → joined Group + membership), the file↔DB identity bridge, and the live scout-burn
   trigger. Needs a live Telethon client; lands coverage-omitted with an in-memory fake.
2. **D4 HTTP surface + the `/v1/cases` CRUD group** — make seed-roots operator-editable.
3. **Group G — Write surface** — idempotency middleware + event-log tables + persona merge/split.

Recommend **E5 (+ the `/v1/cases` CRUD that unblocks D4's endpoints)**.

---

## How to resume

```bash
cd /home/anti/Tools/EYENET
git log --oneline -8
.venv/bin/pytest -m "unit or contract" -q                       # fast inner loop
.venv/bin/pytest -m "unit or contract or integration" -q        # full (8 known §3.3 flakes)
```

Deep refactor / new milestone → worktree branch + atomic `--no-ff` merge (CLAUDE.md §6).
