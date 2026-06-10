# PHASE-2 — Group B / M9.B1: signing-key registry + acknowledgment nonces

**Status:** ✅ SHIPPED (worktree `worktree-e55-requested-to-joined`, un-merged — series checkpoint)
**Date:** 2026-06-09
**PLAN item:** API_PLAN.md Group B / M9.B1 (§5.5–5.7) — the cryptographic foundation of the file-access journal. First of three B-slices (B2 = journal table + byte-serving, B3 = exoneration endpoint).

## What shipped
The verify-side foundation for Ed25519-signed file access:
- **Two tables in `audit.db`** (`eyenet/models/file_access.py`, routed via `_AUDIT_TABLES` in `sqlite_repo/database.py` — co-located with `audit_log` per §5.5): `system_user_signing_pubkey_history` (rotation trail, one active key per user) and `file_access_acknowledgment` (single-use 60s nonces).
- **Storage mixin** `eyenet/storage/sqlmodel_repo/file_access.py`: `record_signing_key`, `lookup_key_for_user(user_id, fingerprint)`, `active_signing_key_for`, `record_acknowledgment`, `consume_acknowledgment` (atomic CAS). Declared on `BaseRepository`.
- **Crypto primitives** `eyenet/crypto/_file_access_signing.py` (re-exported from `eyenet/crypto/__init__.py`): `fingerprint` (sha256 of DER SPKI, 8-byte), `build_canonical` (`EYENET-SIG-v1`, fully length-prefixed framing), `verify_signature` (verify-only, non-bytes-safe).

## Decisions made (and why)
- ✅ **Verify-only** — B1 holds only public keys + verification. Private-key-at-rest and the **server-side-signing-vs-client-signing fork are DEFERRED to the B2 checkpoint** (both models need only the pubkey registry, which B1 provides).
- ✅ **User-scoped key resolution** `lookup_key_for_user(user_id, fingerprint)` + composite `UNIQUE(user_id, fingerprint)` — fingerprint-only lookup with `.first()` could attribute a signature to the WRONG user (two users sharing a raw key is an operational path, not just a hash collision). In a non-repudiation journal, attribution must be unambiguous. Verification always knows the authenticated asserting user.
- ✅ **One-active-key enforced by a SQLite partial-unique index** `ON (user_id) WHERE retired_at IS NULL`, created in the `sqlite_repo` backend DDL (NOT the model/mixin — keeps them ANSI-clean per Rule 1; future backends add their own). Retire+insert run in ONE `safe_session` transaction → on the index firing, the whole tx rolls back and the prior key stays active (no zero-active-keys window). `active_signing_key_for` reads `ORDER BY set_at DESC, id DESC` (uuid7 = monotonic tiebreak), never `.one()`.
- ✅ **Injection-proof canonical form** — every component (incl. the scheme tag) is `len(4-byte BE) + bytes`, so the signing string is a structurally injective function of the field tuple; oversized field raises `OverflowError` (no silent truncation). Domain-separated by the versioned tag inside the signed bytes.
- ✅ **Atomic nonce single-use** — `consume_acknowledgment` is a conditional `UPDATE ... WHERE nonce AND consumed_at IS NULL AND expires_at > now` (rowcount==1), mirroring the Phase-1 CAS. Double-spend + expiry rejected atomically.

## Validation
- Tests: `python -m pytest -m 'unit or contract' -q` → **1972 passed**, 1 pre-existing unrelated failure (`test_scopes_revoke_removes_grant`, live-NATS). Coverage **88.36%** (gate 84). New tests: `tests/unit/storage/test_file_access_keys.py` (deterministic fingerprint, rotation retire+both-resolve, **user-scoped no-cross-attribution**, rapid-rotation deterministic-newest, **partial-unique index fires on 2 active**), `tests/unit/storage/test_file_access_acknowledgment.py` (consume-once / double-spend / expiry / unknown), `tests/unit/crypto/test_file_access_signing.py` (DER fingerprint vector, tamper/wrong-key/malformed/non-bytes rejection, injectivity incl. `|`-join + NUL-shift, stability).
- Lint/type: `ruff format` + `ruff check` clean; `mypy --strict eyenet/` clean (417 files).
- Adversarial review: **2 rounds, crypto-boundary UNANIMOUS-solid bar.** R1: storage reviewer broken (wrong-user attribution; rotation race → 2 active keys) — crypto + scope reviewers solid. R2: both reviewers SOLID (zero-active-keys path refuted — retire+insert is one tx; DDL in all paths; uuid7 tiebreak). One low (no in-suite test that the index *fires*) closed with a dedicated enforcement test.

## State for the NEXT agent (continuation token)
- **Where we are:** B1 (verify-side registry + nonces + crypto primitives) complete and green on the un-merged worktree. Phase-1 (REQUESTED→JOINED, commit 546e710) also on this branch.
- **Next PLAN item:** **M9.B2** (§5.6) — the `file_access_journal` table (mandatory Ed25519 signature column, tier-conditional CHECK constraints) + `record_access()` that signs the canonical form and persists. **The deferred fork resolves at the B2 scoping checkpoint: does the server hold/generate operator private keys (server-side signing, needs `operator_keys/*.priv.enc` + argon2id + ChaCha20) OR does the client sign and the server only verify (B1 already covers verification)?** This decision drives whether B2 builds the private-key-at-rest layer.
- **Gotchas / landmines:**
  - Worktree env: run pytest/mypy via `/home/anti/Tools/EYENET/.venv/bin/python -m ...` from the worktree dir (cwd-shadowing). Sandbox python is 3.14, no deps. See `feedback_worktree_venv_cwd_shadowing`.
  - New audit.db tables are added by listing the tablename in `_AUDIT_TABLES` (`sqlite_repo/database.py`) — exact-string match to `__tablename__`. Dialect-specific DDL (the partial-unique index) lives ONLY in the sqlite_repo backend, created in both `init_audit_db` (sync) and `init_audit_db_async`; the in-memory path uses the sync one.
  - `lookup_key_for_user` resolves active OR retired (a just-rotated key must still verify); B2/B3 verification must pass the authenticated user_id + the `kid` fingerprint.
  - Crypto is verify-only — `build_canonical`/`verify_signature` exist; the SIGNING counterpart does not yet (B2/B3 + the key-storage fork).
  - Note (not ours): `system_user_clearance_grant`'s model docstring claims audit.db but it actually lives in main.db (`_MAIN_TABLES`). Untouched; flag if it matters for B2/B3.
- **Files to start from:** `eyenet/models/file_access.py`, `eyenet/storage/sqlmodel_repo/file_access.py`, `eyenet/crypto/_file_access_signing.py`, `eyenet/storage/sqlite_repo/database.py`, `development/API_PLAN.md §5.6–5.9`.

## Open questions for the human (B2 scoping checkpoint)
- **Server-side vs client-side operator signing** (drives B2 scope — the private-key-at-rest layer).
- Merge cadence: Phase-1 + B1 are checkpoint commits on the worktree, still un-merged to main. Confirm whether to merge the series after B2/B3 or sooner.
