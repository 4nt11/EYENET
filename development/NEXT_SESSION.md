# EYENET — session handoff (2026-05-31)

Start-here note for the next session. Read this, then
`~/.claude/projects/-home-anti-Tools-EYENET/memory/MEMORY.md` and
`development/API_PLAN.md`.

---

## Where we are

- **M10 Document Classifier — DONE + MERGED to `main`.**
  - `524e557` — `--no-ff` merge of all 9 slices.
  - `d67dccf` — coverage baseline ratcheted 0.869 → **0.8906**.
  - `556592b` — `uv.lock` regenerated from PyPI (see below).
  - Current `main` HEAD = `556592b`.
- Battery on main: **1896 passed / 16 skipped / 7 failed**. The 7 are the
  documented §3.3 log-capture flakes (impostor-pool ×3, verifier service-branches
  ×3, stylometric kernel-memo throughput ×1) — all pass in isolation, NOT
  regressions. Coverage 89.06% (gate 84%).
- M10 finished classifier-side: it **assigns** `classifier_tier` to attachments +
  uploaded documents (deterministic MAX of regex / metadata-escalate / Presidio
  floors; LLM flag-only; fail-closed). PII map recalibrated **v2** + ruleset **v4**
  against ANTI's 50-doc real corpus (over-class 0.588→0.137). Full detail:
  `[[project_m10_slice9_done]]` memory + `development/CLASSIFIER_PLAN.md`.

## Environment gotchas (read before running anything)

- **Extract venv is provisioned in dev:** `/home/anti/Tools/EYENET/.venv-extract`
  (Python **3.14**, ABI-matched to the jail interpreter `/usr/bin/python3`).
  Set `EYENET_EXTRACT_VENV=/home/anti/Tools/EYENET/.venv-extract` to run the
  jailed Presidio/extract paths + `eyenet calibrate classify capture`. The main
  dev venv is `.venv` (3.12) — do NOT bind it into the jail (ABI break).
- **`behave-{core,text}` are now ordinary PyPI deps** (0.1.1 / 0.1.3). The old
  `[tool.uv.sources]` local-path override is GONE; `uv sync --all-extras`
  materializes everything from PyPI. The "never regenerate uv.lock" rule is
  RETIRED.
- **Worktree git hooks don't auto-fire:** `core.hooksPath` → `.git/hooks`, not the
  repo's `.githooks/`. Run gates manually before committing/merging. Detect-secrets:
  `detect-secrets-hook --baseline .secrets.baseline --exclude-files
  '^tests/fixtures/calibration/' <files>` (calibration fixtures are excluded;
  test-constant secrets get an inline `# pragma: allowlist secret`).
- **Stray untracked artifacts in the working tree — NEVER commit:**
  `DSR-2026-NH-00417-FICTIONAL.docx`, `classifier_corpus.py`, `docs-1.jsonl`,
  `ruleset-additive.toml`, `development/.$eyenet-erd.drawio.dtmp`. (`docs-1.jsonl`
  is ANTI's 50-doc source corpus; it's already baked into
  `tests/fixtures/calibration/classifier_seed_corpus.jsonl`.)
- Stale `groupF-read-surface` worktree still on disk (M9 leftover) — unrelated,
  `git worktree remove` whenever.

---

## NEXT: close the loop M10 opened — the Documents API surface

M10 stamps the tier; there is **no API to read or act on it**. The `documents/`
route group is upload-only today (`api_upload_document.py` + nothing else). Three
pieces, ideally one milestone (slice-per-commit, worktree + `--no-ff` like M9/M10):

### 1. Document read / list
- New: `eyenet/api/v1/documents/api_get_document.py` (`GET /v1/documents/{id}`) +
  `api_list_documents.py` (`GET /v1/documents`, filtered/paginated).
- **Mirror the Group F read pattern** — `eyenet/api/v1/actors/api_get_actor.py`,
  `api_list_observations.py`. Same dep wiring (`get_storage`, `CurrentUser`).
- **MUST gate through clearance + the evidence-access journal** (§5.5
  evidence-access middleware already exists and gates the other read surfaces; a
  classified document body is byte-level evidence → signed file-access journal
  entry on every serve). Do NOT serve a document body below the requester's
  clearance.
- Storage reads exist: `get_document`. May need a `list_documents` flat method
  (ANSI-only, add to `BaseRepository` + the sqlmodel mixin — re-read CLAUDE.md
  §2.3 before touching storage).

### 2. Document reclassification
- New: `eyenet/api/v1/reclassify/api_reclassify_document.py` — the `reclassify/`
  group has `api_reclassify_observation.py` + `api_reclassify_attachment.py` but
  NO document path. **Mirror the attachment one exactly.**
- Model (`[[project_reclassification_model]]`, API_PLAN §4.9):
  classifier-authoritative, **operator-promote-only**, monotone-up (never demote),
  `admin:reclassify` scope, writes `operator_tier_override`, audited. The
  `DocumentTable` already has the tier-monotone CHECK + `operator_tier_override`
  column.

### 3. Review-flag queue (the human-in-the-loop the flag-only design needs)
- The classifier emits `review_flags` (`POSSIBLE_OVER_CLASSIFICATION`,
  `LLM_HIGHER_TIER`, `LLM_UNAVAILABLE`) and sets `review_required`, but there is
  **no endpoint to list the queue or action a flag** — it dead-ends in a column.
- Build: list flagged documents/attachments (`review_required=true`), and an
  action endpoint (promote via the reclassify path / dismiss). Decide whether
  dismiss needs its own scope + audit subject.
- The `POSSIBLE_OVER_CLASSIFICATION` flag may carry `corroborated=true` (LLM
  agreed NORMAL, slice-9) — surface that to the reviewer.

### Scopes already present
`write:documents` (admin+analyst baseline), `read:classified`, `admin:reclassify`
exist in `eyenet/api/auth/_permissions.py`. Decide if document *read* needs a new
`read:documents` or just rides clearance-tier gating like other entities (likely
the latter — reads gate on clearance, not a per-entity scope).

### Surface-pin discipline
New endpoints must be registered in the hand-drafted OpenAPI yaml
(`contracts/openapi/eyenet.v1.yaml`) + the op-id test in `tests/.../test_app.py`,
and pass the surface-gate (`tests/unit/contracts/test_surface_gate.py`). Coverage
can't trace ASGI-routed handlers → add **direct-call unit tests** per handler under
`tests/unit/api/v1/documents/` (the lesson from `[[project_m9_f_done]]`).

---

## AUDIT FIRST (do this before committing to the above)

I did NOT audit M9 group state this session. `development/API_PLAN.md` structures
M9 as **Groups A–F**; Group A (auth/tokens) and Group F (read surface) are merged
(`[[project_m9_a6_done]]`, `[[project_m9_f_done]]`). The existence of `cases/`,
`clearance/`, `reclassify/`, `identities/`, `panic/`, `stream/`, `metrics/` route
groups suggests B–E largely landed — **but confirm against API_PLAN** before
deciding whether the Documents API is the next milestone or whether an open M9
group takes priority. Also outstanding per memory: M9.2 PAT `read:metrics` scrape
example, M9.6 Grafana dashboard (treat as marketing deliverable).

---

## How to resume

```bash
cd /home/anti/Tools/EYENET
git log --oneline -5                      # HEAD should be 556592b
git status --short                        # only the stray artifacts (never commit)
# read the lay of the land:
#   development/API_PLAN.md   (M9 HTTP API — the source of truth for v1 routes)
#   development/NEXT_SESSION.md (this file)
#   ~/.claude/projects/-home-anti-Tools-EYENET/memory/MEMORY.md
# run the suite (note the 7 known §3.3 flakes):
.venv/bin/pytest -m "unit or contract" -q
# jailed/extract paths need the extract venv:
EYENET_EXTRACT_VENV=/home/anti/Tools/EYENET/.venv-extract .venv/bin/pytest -m integration -q
```

Deep refactors / new milestone → worktree branch + atomic `--no-ff` merge
(CLAUDE.md §6).
