# PHASE-3 — Group B / M9.B2 (storage core): file-access journal append

**Status:** ✅ SHIPPED (worktree `worktree-e55-requested-to-joined`, un-merged — series checkpoint)
**Date:** 2026-06-09
**PLAN item:** API_PLAN.md Group B / M9.B2 (§5.6) — the hash-chained, signature-verifying file-access journal append. Second of three B-slices (B1 done; B3 = byte-serving + exoneration). **Decision (this session): CLIENT-SIDE signing** — the operator's client (eventually the web UI) holds the private key and signs; the server only verifies + records. No UI exists yet, so the signed path is exercised by tests until a client ships.

## What shipped
- **`file_access_journal` table** (`eyenet/models/file_access.py`, audit.db via `_AUDIT_TABLES`): the §5.6 columns incl. mandatory `operator_signature`, `signing_pubkey_fingerprint`, and the hash-chain (`prev_journal_hash`/`self_hash`, 32-byte BLOBs). DB-level tier-conditional CHECK: `grant_id` + `acknowledgment_id` NOT NULL when `tier != NORMAL`.
- **`record_access(...)`** (`eyenet/storage/sqlmodel_repo/file_access.py` + SQLite serialized override in `sqlite_repo/repository.py`): verify the operator's EYENET-SIG-v1 signature (B1 `lookup_key_for_user` + `verify_signature`) → freshness check → atomically consume the acknowledgment nonce + chain-append the row, all in ONE `BEGIN IMMEDIATE` transaction under the shared `_audit_write_lock`. Fail-closed at every gate.
- **`verify_file_access_chain()`** — walks the journal, recomputes each `self_hash`, confirms linkage.
- New crypto primitive `build_journal_row_canonical` (`EYENET-FAJ-v1`, length-prefixed) for the row hash — distinct from the request-signing `EYENET-SIG-v1`.

## Decisions made (and why)
- ✅ **Journal = a second hash chain in audit.db, written by the same single-writer mechanism as the audit log** (`_append_audit_locked` pattern, §2.6). Mixin holds generic logic; the `BEGIN IMMEDIATE` raw-cursor serialization is the SQLite override (Rule 1). Genesis = 32 zero bytes.
- ✅ **Two distinct canonicals, domain-separated** — request signature (`EYENET-SIG-v1`, verified, never hashed into the chain) vs row hash (`EYENET-FAJ-v1`, hashed, never verified as a signature). Different tags ⇒ no cross-protocol preimage.
- ✅ **Nonce-consume is ATOMIC with the chain append** (round-2 fix) — both the conditional `UPDATE file_access_acknowledgment` and the journal INSERT run in the same `BEGIN IMMEDIATE`; any failure rolls back BOTH (nonce stays unconsumed/retryable, no orphan row). Replaced a non-atomic version that could burn the nonce with no journal row (fail-OPEN for non-repudiation) or leave a row with an unconsumed nonce (double-spend). **Atomicity depends on all three tables being in audit.db — verified in `_AUDIT_TABLES`.**
- ✅ **Freshness/replay window in `record_access`** (round-2 fix) — parse `sig_timestamp` (ISO 8601) after verify; reject if unparseable or `|now - ts| > 300s`. Closes the otherwise-unbounded NORMAL-tier replay (NORMAL has no nonce).
- ✅ **`record_access` is storage-core**: caller supplies `content_hash`/signature/`sig_*` fields; it enforces the tier CHECK (grant present for non-normal) and records — verifying the grant actually *authorizes* is B3 tier-gating.

## Validation
- Tests: `python -m pytest -m 'unit or contract' -q` → **1989 passed**, 1 pre-existing unrelated failure (`test_scopes_revoke_removes_grant`, live-NATS). Coverage **88.45%** (gate 84). New: `tests/unit/storage/test_file_access_journal.py` (happy/chain/genesis, tamper→chain-broken, invalid-sig & wrong-content_hash & unknown-key rejected, tier-conditional, **failed-append-leaves-nonce-retryable**, **concurrent-same-nonce→exactly-one-row**, freshness stale/fresh/unparseable) + `test_file_access_journal_sqlite.py` (DB CHECK probe, `_sqlite`-pinned).
- Lint/type: `ruff format`/`check` clean; `mypy --strict eyenet/` clean (417 files).
- Adversarial review: **2 rounds, unanimous-solid bar.** R1: chain+scope solid; crypto/consistency reviewer broken (nonce/append non-atomic MED; replay LOW). R2: all reviewers SOLID (atomicity refuted — one tx, both roll back, rowcount reliable; freshness fail-closed; chain linear). Lynchpin (ack table in audit.db) verified directly.

## State for the NEXT agent (continuation token)
- **Where we are:** B1 + B2 storage core complete and green on the un-merged worktree. The journal can verify a client signature, atomically consume a nonce, and append a tamper-evident row. No HTTP surface yet.
- **Next PLAN item:** **PHASE-4 = M9.B2 HTTP surface + key registration**, OR **B3** (§5.8) — decide at the next scoping checkpoint. The natural PHASE-4: (1) a **public-key registration/enrollment endpoint** (client generates keypair, uploads pubkey + proof-of-possession = sign a B1 acknowledgment-nonce challenge → `record_signing_key`) — REQUIRED before any signed access can verify; (2) the `POST /v1/attachments/{blob_id}/access` + `GET .../manifest` handlers that read the `X-Operator-Signature`/`kid` headers, mint/return the acknowledgment nonce, and call `record_access`. B3 = actual byte-serving + tier/clearance gating + exoneration queries (§5.8) + external anchoring (§5.9).
- **Gotchas / landmines:**
  - Worktree env: `/home/anti/Tools/EYENET/.venv/bin/python -m ...` from the worktree dir (cwd-shadowing). Sandbox python is 3.14. See `feedback_worktree_venv_cwd_shadowing`.
  - **`record_access` freshness assumes an aware `now`.** Default `now=datetime.now(UTC)` is aware; a caller passing a NAIVE `now` would hit an uncaught `TypeError` in the `abs(now - ts)` subtraction (the `except` only wraps `fromisoformat`). PHASE-4 handler MUST pass a tz-aware `now` (or add a one-line coerce-naive-to-UTC at the top of the freshness block). Currently unreachable (no production caller).
  - **NORMAL-tier in-window replay residual:** within 300s the same signed NORMAL request replays → duplicate (operator-signed) journal rows. No `request_id` dedup (the column isn't even stored). If undesired, add `UNIQUE(user_id, sig_request_id)` or store+dedup request_id — a PHASE-4 call.
  - HTTP header names for the signature/`kid` are NOT specced — PHASE-4 must define them (`X-Operator-Signature: EYENET-SIG-v1 ed25519=<b64>; kid=<16hex>` is the working assumption).
  - The two canonicals MUST stay distinct (`EYENET-SIG-v1` request vs `EYENET-FAJ-v1` row) — never feed one to the other's consumer.
- **Files to start from:** `eyenet/storage/sqlmodel_repo/file_access.py` (`record_access`), `eyenet/crypto/_file_access_signing.py`, `eyenet/api/v1/attachments/` (handler stubs), `development/API_PLAN.md §5.6–5.9`.

## Open questions for the human (PHASE-4 scoping checkpoint)
- PHASE-4 scope: fold in the key-registration endpoint + the access/manifest handlers together, or split registration from the access handlers?
- Merge cadence: Phase-1 + B1 + B2 are checkpoint commits, still un-merged to main. Merge the series after B3, or sooner?
