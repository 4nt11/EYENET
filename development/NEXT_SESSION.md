# EYENET — session handoff (2026-06-06, pm)

Start-here note. Read this, then
`~/.claude/projects/-home-anti-Tools-EYENET/memory/MEMORY.md` and
`development/API_PLAN.md`.

---

## Where we are

- **`/v1/cases` CRUD + D4 seed-roots + M9.E5 Telegram recursion — DONE.**
  Worktree branch `worktree-cases-d4-e5`, slice-per-commit, `--no-ff` merge.
- Battery: `unit or contract or integration` = **2051 passed / 16 skipped / 6 failed**.
  The 6 are the documented §3.3 verifier log-capture flakes
  (`test_impostor_pool_loader` ×3 + `test_service_branches` ×3) — **all pass in
  isolation** (`8 passed`), no verifier code was touched, NOT regressions.
  Coverage **90.98%** (gate 84%; baseline `.coverage-baseline` 0.8906 → no-drop
  satisfied, up). ruff/mypy --strict (413 files)/bandit (0)/deptry/detect-secrets
  all clean.

### `/v1/cases` CRUD (Slices A–D)
- Storage `list_cases`/`count_cases` added (mirrors `list_candidates`); §4.10.4
  collaborator list-visibility predicate lives in storage.
- All 15 handlers filled (`eyenet/api/v1/cases/api_*.py`) over the already-complete
  `CasesMixin`. **Case storage methods self-audit the hash-chain row** (no bus emit
  — that's Group H); handlers pass attribution via `cases/_detail.py:audit_ctx`
  and do NOT double-emit. Creator auto-enrolled as OWNER collaborator.
- New storage `reopen_archived_case` (archived→open mints a `parent_case_id`
  successor). Scopes: read/write:cases + `admin:case` (archive, collaborators).
- `CaseCollaboratorRevokeRequest.revocation_reason` min 1→16 (was a 422-vs-409 wart).
- D4: `GET/PUT /v1/cases/{id}/seed-roots` + `POST .../seed-roots/{group_id}` over
  `update_case_discovery_policy`; eligibility recompute is implicit (the §4.12.3
  predicate reads the live set — proven by a `resolve_case_for_candidate` shift test).
- OpenAPI surface-pin updated (3 ops + `CaseSeedRoots`/`CaseSeedRootsReplaceRequest`).

### M9.E5 Telegram recursion (Slices E1–E4)
- **Decisions (operator):** bus command channel (supervisor publishes); FULL
  scout/monitor separation (command keyed to the leased scout's `instance_id`);
  ban-on-join → `joining→failed` + burn (candidate never reached `joined`); scout
  role signal = optional `role` field in `identities.toml`.
- `command_subject_for(scout_instance_id)` = `eyenet.control.collector.{id}.command`;
  new `CANDIDATE_JOINED`/`CANDIDATE_FAILED` audit subjects.
- Supervisor `dispatch_approved` now **publishes** the `JoinGroupCommand` (raw
  `bus.publish` — it's a bare BaseModel, not a BusEnvelope) after the joining
  transition + `candidate.joining` audit (kept as the record of intent).
- **Telethon-free join core** `eyenet/collectors/telegram/_join.py` (coverage-
  credited): `classify_join_error(exc_name)` switches on the telethon error CLASS
  NAME (import-free); `CollectorJoinHandler` does finalize_joined / fail_candidate /
  quarantine_on_ban (burn scout via `ScoutGraduationService` + file-pool BURNED
  release so restart-recovery can't re-offer it). `real.py` is the coverage-omitted
  telethon glue (`_handle_join` issues `JoinChannelRequest`).
- file↔DB bridge: optional `role` on `IdentityFileEntry`; `provision_identities()`
  (`eyenet/services/discovery/identity_provisioning.py`) + `eyenet identity sync`
  CLI. After sync, `has_available_scout()` is true → loop runs end-to-end.

## What's still open

- **E5.5 — access-artifact join path:** `_handle_join` only does the public-identifier
  `JoinChannelRequest` (`access_artifact_id is None`). Invite-link / QR / artifact-kind
  dispatch (`ImportChatInviteRequest`, MODELS §2.24 selection + a `get_access_artifact`
  storage getter) + the supervisor setting `access_artifact_id` are deferred. Unsupported
  artifact kinds currently `fail_candidate("unsupported_access_artifact")`.
- **Live ban-on-the-wire → quarantine:** `quarantine_on_ban` is wired for the *join*
  path; a ban detected LATER on the live message/health path (403s on an
  already-joined group → `joined→parked` + close membership) is not yet wired.
- **`joining` redelivery:** a crash between the supervisor's transition and publish
  leaves a candidate in `joining` with no retry rescan (the collector is the source
  of truth for the next transition). A supervisor `joining`-rescan is a follow-up.
- **Supervisor structural-fail surfacing** (OVER_DEPTH / SKIP_DUAL_COVER /
  NO_REACHABLE_ROOT) still only logs — no operator-facing surface (Group H stream).
- **Cases:** bulk member ops are best-effort sequential (stop on first conflict, no
  rollback); `audit_event_ids` in `CaseMemberBulkResult` is empty (storage self-audits
  internally, ids not surfaced). Soft-removed member/collaborator listing (`active_only`)
  not exposed. Case mutations write the audit DB row but don't emit a bus AuditEvent
  (stream:audit is Group H).

## Environment gotchas

- **Worktree venv trap:** the shared `.venv` editable install (`_editable_impl_eyenet.pth`)
  points at a STALE deleted worktree (`groupA-auth-tokens`), so `eyenet` only resolves
  via cwd-shadowing. ALWAYS run tests as `cd <worktree> && .venv/bin/python -m pytest …`
  (never the bare `.venv/bin/pytest` console script — no cwd on sys.path → wrong tree).
  Use `--no-cov` for fast inner-loop runs (the `--cov-fail-under=84` fails per-file runs).
- **telethon IS installed** (1.43.2) — `real.py` imports fine; the recon's "not installed"
  claim was wrong. The `_join.py` extraction still earns coverage credit + clean separation.
- ASGI / shared in-memory aiosqlite: seed all `await storage` state BEFORE the first
  TestClient call (MissingGreenlet). `active_case_id` pydantic serializer UserWarning on
  every collaborator op is pre-existing (in `add_case_collaborator`), harmless.
- §3.3 flakes: confirm any failure under `-p no:randomly` + in isolation before treating
  as a regression. The 6 verifier ones are known offenders.
- Stray untracked artifacts — NEVER commit: `DSR-2026-NH-00417-FICTIONAL.docx`,
  `classifier_corpus.py`, `docs-1.jsonl`, `ruleset-additive.toml`, `development/.$eyenet-erd.drawio.dtmp`.

---

## NEXT: candidates for the follow-up milestone

1. **E5.5 — access-artifact join path** — invite-links/QR + supervisor artifact selection;
   closes the join story for private groups.
2. **Group G — Write surface** — idempotency middleware + event-log tables + persona
   merge/split.
3. **Group H — Stream surface** — SSE for candidate.* / case.* / audit; surfaces the
   supervisor structural-fail verdicts + case-audit bus events.

---

## How to resume

```bash
cd /home/anti/Tools/EYENET
git log --oneline -8
.venv/bin/python -m pytest -m "unit or contract" -q --no-cov              # fast inner loop
.venv/bin/python -m pytest -m "unit or contract or integration" -q        # full (6 known §3.3 flakes)
```

Deep refactor / new milestone → worktree branch + atomic `--no-ff` merge (CLAUDE.md §6).
Heed the worktree venv trap above: `python -m pytest` from inside the worktree.
