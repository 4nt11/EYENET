# PHASE-1 — REQUESTED→JOINED membership resolution

**Status:** ✅ SHIPPED (worktree `worktree-e55-requested-to-joined`, un-merged — awaiting `--no-ff` to main)
**Date:** 2026-06-09
**PLAN item:** Post-E5.5 #1 loose end (named in `project_m9_e55_done.md`): "nothing flips REQUESTED→JOINED yet (needs live membership detector)". Closes the hole opened by the E5.5 invite-link join path (commits b6bff90 / 3b70b99 / e2118a2).

## What shipped
When an approval-gated Telegram join is actually approved by an admin, the candidate now flips `CandidateState.REQUESTED → JOINED` **and** the `CollectorGroupMembership` row is opened. One telethon-free decision core with two live callers:
- **Core** (`eyenet/collectors/telegram/_join.py`): `confirm_requested_membership(...)` — atomic CAS-first transition, opens membership, emits `candidate.joined` audit, idempotent, with failure compensation. Shares `_open_joined_membership(from_state=...)` with `finalize_joined`.
- **Storage** (`eyenet/storage/sqlmodel_repo/candidates.py`): atomic `claim_candidate_transition(...)` CAS (conditional UPDATE WHERE id AND state) + `requested_candidates_for_collector` / `requested_candidate_for_group` queries. Declared on `BaseRepository`.
- **Event path** (`real.py`, coverage-omitted): a message from a chat matching a REQUESTED candidate ⇒ confirm. Primary, cheap.
- **Probe backstop** (`real.py` `tick()`, throttled 300s): `@username`/numeric via `GetParticipantRequest('me')`; invite-link via `CheckChatInviteRequest`→`ChatInviteAlready`.

## Decisions made (and why)
- ✅ **Detector lives in the collector, not the supervisor** — only the collector holds the telethon client to verify membership. Supervisor can't.
- ✅ **Atomic CAS, transition-FIRST** — `transition_candidate` was SELECT-then-UPDATE (not atomic); two callers (event+probe) could both open membership. CAS `UPDATE ... WHERE state=:from` (rowcount==1) makes exactly one caller win. Rejected: a partial unique index on active membership (dialect-specific `WHERE` clause → Rule-1 leak; CAS is ANSI-generic).
- ✅ **Invite-link (`joinchat:<hash>`) candidates are PROBE-ONLY** — the numeric `chat_id` from an incoming message cannot reconstruct the invite hash, so the event path structurally cannot correlate them. Forced platform limitation, not a preference. Probe uses `CheckChatInviteRequest`; only `ChatInviteAlready` confirms (pending `ChatInvite` does not).
- ✅ **Genuine membership check, not resolvability** — `get_entity` resolves a public channel whether or not you're a member; using it would fabricate JOINED on still-pending joins. Use `GetParticipantRequest('me')`/`UserNotParticipantError`.
- ✅ **Case-folding** — discovery stores `@{username.lower()}`; event-path forms are lowercased to match (exact-equality query).
- ✅ **Failure compensation (self-healing, never silent)** — CAS commits JOINED first; if `open_membership` then fails, raw-CAS roll back JOINED→from_state + loud WARN + re-raise (probe retries next sweep). If audit-emit fails *after* membership opened: no rollback (membership is the durable evidence) + loud WARN + re-raise. Order: membership (main.db) before audit (audit.db/bus).
- ✅ **Per-candidate sweep isolation** catches `(RuntimeError, RPCError, ValueError, SQLAlchemyError)` → log+continue. One dead/renamed channel (raises plain `ValueError`) or a transient DB lock must not starve the rest of the sweep.

## Validation
- Tests: `python -m pytest -m 'unit or contract' -q` → **1949 passed**, 1 pre-existing unrelated failure (`test_scopes_revoke_removes_grant`, live-NATS ConnectionRefused — not in this diff). Coverage **88.28%** (gate 84). New tests in `tests/unit/collectors/test_telegram_join.py` (core, CAS-first idempotency, dual-caller exactly-one, compensation rollback, audit-fail-keeps-membership, no-collector RuntimeError, pure `candidate_match_forms`) and `tests/unit/storage/test_candidates.py` (CAS winner/loser/wrong-from-state/missing).
- Lint/type: `ruff format` + `ruff check` clean; `mypy --strict eyenet/` clean (413 files).
- Adversarial review: **3 rounds.** R1: 2/3 broken (matching dead for joinchat+CamelCase, probe false-positive, double-membership race, hot-path regression, sweep fragility). R2: 2/2 broken (silent JOINED-without-membership; `get_entity` ValueError aborts sweep; event-path staleness). R3: **solid** (1 med + 2 low, all self-limiting). Med (storage exception aborting sweep) fixed in a final pass. All findings resolved.

## State for the NEXT agent (continuation token)
- **Where we are:** REQUESTED→JOINED resolution is complete and green on the un-merged worktree branch. The E5.5 approval-gated join loop now closes end-to-end.
- **Next PLAN item:** per `development/API_PLAN.md`, the next unstarted M9 group is **Group B — File-access journal (M9.B1–B3)** (Ed25519-signed byte-serving + exoneration queries, §5.6–5.9). Group G (write surface) and H (streaming) follow. (Confirm against `git log` at pickup.)
- **Gotchas / landmines:**
  - Worktree env: NO own `.venv`; run pytest/mypy via `/home/anti/Tools/EYENET/.venv/bin/python -m ...` from the worktree dir (cwd-shadowing). A bare/sandbox python is 3.14 with no deps and collection-errors. See `feedback_worktree_venv_cwd_shadowing`.
  - The CAS `claim_candidate_transition` does NOT clear a column passed `None` (only SETs when not-None) — so a rolled-back REQUESTED candidate keeps a stale `resulting_group_id`. Confirmed benign (readers get a truthful empty membership list; overwritten on next success). Don't "fix" it without checking the rollback path.
  - The compensation rollback uses the RAW CAS deliberately, bypassing the FSM `_ALLOWED` guard — it is a failure-compensation edge and must NOT be added to `_ALLOWED`.
  - real.py event/probe wiring is coverage-omitted (§3.4, live-service-only). The testable seam is the pure core + `candidate_match_forms`.
- **Files to start from:** `eyenet/collectors/telegram/_join.py`, `eyenet/storage/sqlmodel_repo/candidates.py`, `eyenet/collectors/telegram/real.py`.

## Open questions for the human (if any)
- Merge gate: this phase is committed-ready on the worktree but **NOT yet committed or merged**. Confirm whether to (a) commit + `git merge --no-ff` to main now, or (b) continue the loop into Group B on the same worktree and merge as a series. (Two stale already-merged worktrees — `cases-d4-e5`, `groupF-read-surface` — are pending `git worktree remove` cleanup, unrelated to this work.)
