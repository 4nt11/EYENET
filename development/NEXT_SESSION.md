# EYENET — session handoff (2026-05-31)

Start-here note. Read this, then
`~/.claude/projects/-home-anti-Tools-EYENET/memory/MEMORY.md` and
`development/API_PLAN.md`.

---

## Where we are

- **M9 Group D — Discovery API surface (D1–D3) — DONE + MERGED to `main`.**
  - Worktree `worktree-groupD-discovery-api`, slice-per-commit, `--no-ff` merge.
  - Slices: storage gaps `cd7c9f2`, D1 Sources `558b7f5`, D2 Collectors `1dee40c`,
    D3 Candidate triage `a2b94f6`, surface-pin/docs/smoke `<slice4>`.
  - **D4 (seed-roots + `Case.auto_join_policy`) DEFERRED** — mutates the Case model and
    its eligibility-recompute couples to the unbuilt Group E runtime. Lands with E.
- 24 endpoints over Group C's discovery storage: `/v1/sources` (9), `/v1/collectors` (9),
  `/v1/candidates` (6). All scope-gated, audited, OpenAPI-pinned (surface test green),
  with direct-call unit tests + an ASGI smoke test (`tests/integration/api/test_discovery_surface.py`).
- Battery: full `unit or contract or integration` run = **1952 passed / 16 skipped / 7 failed**.
  The 7 are the documented §3.3 log-capture flakes (impostor-pool ×3, verifier
  service-branches ×3, stylometric kernel-memo ×1) — all pass in isolation, NOT regressions.
  Coverage **89.59%** (gate 84%; `.coverage-baseline` left at 0.8906 — no-drop satisfied, not
  ratcheted to avoid the unit-only-vs-full measurement mismatch).

## Group D as-built deviations (all documented in code + API_PLAN §Group D)

- **Eligibility is a STUB.** `eyenet/services/discovery/eligibility.py` returns
  `DEFERRED_TO_RUNTIME` per mentioning collector; `POST /v1/candidates/{id}/approve` does
  **NOT** enforce an eligibility gate (validates existence + assigned_collector_id + legal
  state transition only). The real predicate (dedup/depth/scout availability) lands with
  **Group E**. This is a deliberate, documented weaker-safety v1.
- Deferred for lack of Group C storage / by design: `DELETE /v1/sources/{id}` (needs
  `delete_source` + multi-table FK guard), atomic initial-`domains[]` POST, `?force`/`?hard`
  bypasses, domain-notes PATCH, collector `pause` (no enum), `?include_left` memberships,
  config discriminated-union.
- Storage added this milestone: `update_source`, `list/count_sources`, `list_source_domains`,
  `swap_source_domain_primary`, `source_bridge_summary`; collector `count`/`update`/paginated
  `list`/`collector_fleet_health`; candidate filtered `list`/`count`; `FAILED→QUEUED` retry edge.

## Environment gotchas

- Extract venv: `/home/anti/Tools/EYENET/.venv-extract` (py3.14); set
  `EYENET_EXTRACT_VENV=...` for jailed Presidio/extract paths.
- **Worktree git hooks don't auto-fire** (`core.hooksPath`→`.git/hooks`). Run gates manually:
  `ruff format --check && ruff check && mypy --strict eyenet && bandit -c pyproject.toml -r eyenet
  && detect-secrets-hook --baseline .secrets.baseline <files> && pytest`.
- **ASGI integration tests:** seed all `await storage` state BEFORE the first TestClient call —
  the in-memory aiosqlite connection is shared across loops; interleaving raises MissingGreenlet.
- Stray untracked artifacts — NEVER commit: `DSR-2026-NH-00417-FICTIONAL.docx`,
  `classifier_corpus.py`, `docs-1.jsonl`, `ruleset-additive.toml`, `development/.$eyenet-erd.drawio.dtmp`.

---

## NEXT: candidates for the follow-up milestone

M9 group map (confirmed against merge commits): A ✅, B ⚠ partial (file-access journal —
`evidence_access.py` middleware landed with F; §5.6 signed journal open), C ✅, **D1–D3 ✅
(this session)**, E ❌ open, F ✅, G ⚠ (idempotency + event-log spine open), H ⚠ (501 stream
stubs), I ⚠ (rate-limit/CORS/metrics partial). Strong candidates:

1. **Group E — Discovery runtime** — the natural pair for D. CollectorSupervisor service,
   `url_extraction` / `channel_reference_extraction` sensor primitives, scout graduation,
   Telegram recursion. **This is what turns the D3 eligibility stub into a real gate** and
   makes `approve` actually execute a join. Also unblocks **D4** (seed-roots + auto-join).
2. **Documents API** — the M10 read/reclassify/review-queue surface (still unbuilt; the
   original handoff target before "groups" took priority).
3. **Group G — Write surface** — idempotency middleware + event-log tables + persona merge/split.

Recommend **Group E (+ D4)** — it closes the discovery loop D1–D3 opened and retires the
eligibility stub. Also outstanding: M9.2 PAT `read:metrics` scrape example, M9.6 Grafana
dashboard (marketing deliverable).

---

## How to resume

```bash
cd /home/anti/Tools/EYENET
git log --oneline -6
.venv/bin/pytest -m "unit or contract" -q                       # fast inner loop
.venv/bin/pytest -m "unit or contract or integration" -q        # full (7 known §3.3 flakes)
```

Deep refactor / new milestone → worktree branch + atomic `--no-ff` merge (CLAUDE.md §6).
