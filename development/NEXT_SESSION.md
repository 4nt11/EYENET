# EYENET — session handoff (2026-06-06, eve)

Start-here note. Read this, then
`~/.claude/projects/-home-anti-Tools-EYENET/memory/MEMORY.md` and
`development/API_PLAN.md`.

---

## Where we are

- **M9.E5.5 — access-artifact join path — DONE.** Worktree branch
  `worktree-e5.5-artifact-join`, slice-per-commit (A–E), `--no-ff` merge
  `1f6cdea`. Worktree + branch removed.
- Battery: `unit or contract or integration` = **2081 passed / 16 skipped /
  8 failed**. The 8 are the documented §3.3 flakes — the 6 verifier
  log-capture ones (`test_impostor_pool_loader` ×3 + `test_service_branches`
  ×3) **plus** `test_stylometric_kernel_memo` ×2 (CLAUDE.md §3.3 names the
  memo/throughput tests too; the E5 memory notes "7–8 jitter"). **All 8 pass
  in isolation** (`8 passed`), no verifier/stylometric code was touched — NOT
  regressions. The 16 skips are the `eyenet-extract` venv classifier tests.
- Coverage **91.03%** (gate 84%; `.coverage-baseline` 0.8906 → no-drop
  satisfied, up — baseline NOT bumped, consistent with the E5 merge). ruff
  format+check / mypy --strict (413 files) / bandit (0) / deptry /
  detect-secrets all clean (baseline got only a line-shift, no new secrets).

### What E5.5 shipped (Slices A–E)
- **Slice A — storage** (`sqlmodel_repo/artifacts.py` + ABC): three generic-ORM
  methods — `get_group_access_artifact`, `list_group_access_artifacts_for_candidate`
  (unordered; ranking is the supervisor's job), `set_artifact_validation_state`
  (dead-link writeback). No dialect leak.
- **Slice B — `CandidateState.REQUESTED`** for approval-gated joins. `_ALLOWED`:
  `JOINING→REQUESTED` (entry) + `REQUESTED→{JOINED,FAILED,PARKED}`. `ck_candidate_state`
  CHECK + OpenAPI `CandidateState` enum pin updated (uppercase NAME in the CHECK,
  lowercase in the yaml). New audit subject `CANDIDATE_JOIN_REQUESTED`.
- **Slice C — telethon-free `_join.py`** (coverage-credited): `JoinOutcome.REQUESTED`
  + `classify_join_error` maps `InviteRequestSentError`; `JoinAction` enum +
  `select_join_action(kind)` (PUBLIC / INVITE_HASH / UNSUPPORTED — **invite-link-only
  scope**, QR + others UNSUPPORTED); `parse_invite_hash` (t.me/+, /joinchat/,
  tg://join?invite=); `artifact_state_for_error` (Expired→EXPIRED, Invalid→REVOKED,
  else None); handler `mark_join_requested` + `record_artifact_validation`.
- **Slice D — supervisor selection** (`collector_supervisor.py`): pure
  `select_access_artifact(artifacts)` — cheapest usable by `_KIND_PREFERENCE`
  (public<invite), filtering `{VALID,UNVERIFIED}` + not `requires_admin_approval`
  + collector-actionable kinds; `None` → public fallback. Wired into
  `dispatch_approved`; the chosen `access_artifact_id` rides the published
  `JoinGroupCommand` (captured in the `candidate.joining` audit for free).
- **Slice E — `real.py` `_handle_join`** (coverage-omitted glue): `_resolve_join_target`
  (fetch→select→parse, fails cleanly on missing/unsupported/unparseable) +
  `_handle_join_error` (ban→quarantine, request-sent→requested, else fail +
  dead-link writeback). INVITE_HASH → `ImportChatInviteRequest`; PUBLIC →
  `JoinChannelRequest`. Two helpers extracted to stay under the branch limit.

## Operator decisions baked into E5.5
1. **Invite-link ONLY.** QR_CODE + direct/paid/blocked/other → UNSUPPORTED →
   `fail_candidate("unsupported_access_artifact")`. QR deferred (needs decode-at-discovery).
2. **Cheapest usable, else public fallback** for supervisor selection.
3. **Validation-state writeback YES** on dead links (expired/revoked).
4. **Real `REQUESTED` state** for `InviteRequestSentError` (not folded into FAILED).

## What's still open
- **`REQUESTED → JOINED` resolution detector:** nothing flips a pending request
  to joined yet — needs live platform membership detection (poll the group, or
  catch the admit event). The entry + give-up/fail edges are wired; resolution
  is the follow-on. This is the #1 E5.5 loose end.
- **QR_CODE join dispatch:** decode-at-discovery must populate the artifact
  `value` with a usable t.me link first, then `select_join_action` adds QR_CODE.
- **`_KIND_PREFERENCE` ↔ `select_join_action` coupling:** the supervisor's
  supported-kind set and the collector's actionable set must grow in lockstep
  (both documented in-code). A shared source would be cleaner if a 3rd platform lands.
- **Live ban-on-the-wire → `joined→parked`:** still deferred from E5 (403s on an
  already-joined group → close membership). `quarantine_on_ban` only covers the
  join path.
- **`joining`/`requested` redelivery rescan:** a supervisor crash between the
  `joining` transition and the publish leaves a candidate stranded (collector is
  the source of truth for the next transition). A supervisor rescan is a follow-up.
- **Supervisor structural-fail surfacing** (OVER_DEPTH / SKIP_DUAL_COVER /
  NO_REACHABLE_ROOT) still only logs — Group H stream.
- **Cases:** bulk member ops best-effort sequential; `audit_event_ids` empty;
  soft-removed listing not exposed; no bus AuditEvent emit (Group H).

## Environment gotchas
- **Worktree path trap (bit me this session):** when in a worktree, Edit/Read with
  the MAIN-tree absolute path silently edits the WRONG tree — tests pass against
  the unchanged worktree and `git commit` says "nothing to commit". ALWAYS use the
  worktree absolute path (`.claude/worktrees/<name>/…`) for every Edit/Read.
- **Worktree venv:** the `.venv` lives in the MAIN tree only. From a worktree run
  `/home/anti/Tools/EYENET/.venv/bin/python -m pytest …` with **cwd = the worktree**
  (cwd-shadowing resolves `import eyenet` to the worktree). `--no-cov` for inner loop
  (`--cov-fail-under=84` fails partial runs). Never the bare `.venv/bin/pytest`.
- ASGI / shared in-memory aiosqlite: seed all `await storage` state BEFORE the first
  TestClient call (MissingGreenlet).
- §3.3 flakes: confirm any failure under `-p no:randomly` + in isolation before
  treating as a regression. The 8 above are known offenders.
- Stray untracked artifacts — NEVER commit: `DSR-2026-NH-00417-FICTIONAL.docx`,
  `classifier_corpus.py`, `docs-1.jsonl`, `ruleset-additive.toml`,
  `development/.$eyenet-erd.drawio.dtmp`.

---

## NEXT: candidates for the follow-up

1. **`REQUESTED → JOINED` resolution detector** — closes the approval-gated join
   loop E5.5 opened (membership polling or admit-event capture).
2. **Group G — Write surface** — idempotency middleware + event-log tables +
   persona merge/split.
3. **Group H — Stream surface** — SSE for candidate.* / case.* / audit; surfaces
   the supervisor structural-fail verdicts + REQUESTED transitions + case-audit
   bus events.

---

## How to resume

```bash
cd /home/anti/Tools/EYENET
git log --oneline -8
.venv/bin/python -m pytest -m "unit or contract" -q --no-cov              # fast inner loop
.venv/bin/python -m pytest -m "unit or contract or integration" -q        # full (8 known §3.3 flakes)
```

Deep refactor / new milestone → worktree branch + atomic `--no-ff` merge (CLAUDE.md §6).
Heed BOTH worktree traps above: worktree paths for edits, `python -m pytest` from cwd.
