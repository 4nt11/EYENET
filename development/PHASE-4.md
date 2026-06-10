# PHASE-4 — Group B: operator public-key registration (auth boundary)

**Status:** ✅ SHIPPED (worktree `worktree-e55-requested-to-joined`, un-merged — series checkpoint)
**Date:** 2026-06-09
**PLAN item:** Group B prerequisite (NOT specced in API_PLAN — designed this session). Client-side signing model: operators enroll the Ed25519 public key their client generates, so file-access signatures (B2 `record_access`) can verify. Without this, nothing verifies.

## Group B roadmap (decided this session)
Criticality test = **security boundary → isolated phase (unanimous-solid); plumbing → grouped**.
- ✅ PHASE-2 (B1) registry + nonces + verify · ✅ PHASE-3 (B2) journal core · ✅ **PHASE-4 registration (THIS)**.
- 🔴 **PHASE-5** = access/manifest handlers + byte-serving (GROUPED, mechanical) — tier-gating left a visible stub.
- 🔴 **PHASE-6** = tier/clearance gating + §5.5 503 gate (ISOLATED, authz boundary).
- 🔴 **PHASE-7** = server signing-key bootstrap + exoneration §5.8 (ISOLATED — reintroduces a *server-held* keypair).
- 🟢 **PHASE-8** = external anchoring §5.9 (light, groupable / PHASE-7 tail).
Admin-override registration **explicitly rejected** (would skip proof-of-possession → admin could enroll a key they control as another operator → forge that operator's signed accesses; self-service + bootstrap-on-first-login + re-register-rotates cover the real needs).

## What shipped
- **`signing_key_challenge` table** (audit.db via `_AUDIT_TABLES`) + storage `mint_signing_key_challenge` / `consume_signing_key_challenge` (atomic, **user-bound** CAS, 60s TTL).
- **Crypto** `build_signing_key_challenge_canonical` (`EYENET-SIGNING-KEY-CHALLENGE-v1`, length-prefixed, binds nonce **and** pubkey) + `load_ed25519_public_key` (algebraic small-order rejection — see below).
- **Two self-service endpoints** (`Depends(get_current_user)`, no special scope, MFA-enroll pattern): `POST /v1/auth/signing-key/challenge` (mint nonce) + `POST /v1/auth/signing-key` (PoP register). `eyenet.audit.auth.signing_key_registered` on success.
- OpenAPI yaml + surface-pin updated; schemas in `eyenet/api/v1/schemas/auth.py`.

## Decisions made (and why)
- ✅ **Proof-of-possession** — verify the challenge signature against the **submitted** pubkey (not yet registered → un-lookupable). Verify-then-atomic-consume ordering (Ed25519 isn't brute-forceable, so an in-TTL retry of one challenge is harmless; the single-use consume is the replay anchor).
- ✅ **User-bound nonce** — `user_id` (from the authenticated token, never the body) is in the consume WHERE clause → A's nonce can never be consumed by B.
- ✅ **No enumeration oracle** — bad PoP / bad-or-replayed / wrong-user nonce all → generic 401; only malformed base64/length → 422 (schema boundary, never 500).
- ✅ **Algebraic small-order key rejection** (the headline fix) — replaced a hand-enumerated byte blocklist (incomplete + backend-dependent) with RFC 8032 point decode: length 32 → canonical `y < p` → on-curve → reject if `8·P == identity`. Backend-independent, exhaustively covers the 8-torsion subgroup.
- ✅ **Re-registration rotates** via B1's `record_signing_key` (prior key retired, one-active invariant) — no separate rotation endpoint needed.

## Validation
- Tests: `pytest -m 'unit or contract' -q` → **2021 passed**, 1 pre-existing unrelated failure (live-NATS flake). Coverage **88.43%** (gate 84). Integration 168 passed. Surface-pin ✓. mypy --strict + ruff clean (420 files).
- New tests: storage (mint/consume/replay/**wrong-user**/expired), crypto (canonical binding + distinct tag; **full 8-torsion rejected**, both proven bypass vectors rejected, non-canonical/off-curve rejected, **100 generated keys accepted + verify**), registration-logic (malformed/all-zeros/invalid-PoP/wrong-user fail-closed), ASGI (challenge→sign→register→resolve; replay→401; wrong-user→401; bad-PoP→401; malformed→422; unauth→401; re-register rotates).
- Adversarial review: **2 rounds, auth-boundary unanimous-solid.** R1: user-binding + API solid; crypto reviewer **BROKEN** — proved end-to-end that two non-canonical identity encodings (`0x0100…0080`, `0xeeff…ffff`) passed the byte blocklist and a forged R=identity‖S=0 signature verified → an attacker could register a key nobody controls → forge file-access signatures. R2 (re-verified by execution): all SOLID — full 8-torsion rejected with zero survivors, zero valid-key false-rejects, bypass closed at the register seam.

## State for the NEXT agent (continuation token)
- **Where we are:** B1+B2 storage/crypto core + PHASE-4 registration endpoint all green, un-merged. An operator can now enroll a key with airtight PoP; `record_access` can verify against it. Still no file-serving HTTP surface.
- **Next PLAN item:** **PHASE-5 = access/manifest handlers + byte-serving** (grouped, mechanical). `GET /v1/attachments/{id}/manifest` (mint+return the B1 acknowledgment nonce for the two-step flow) + `POST /v1/attachments/{id}/access` (read `X-Operator-Signature`/`kid` headers, call `record_access`, then stream bytes + compute `content_hash`/`content_size` live). **Tier/clearance gating stays a visible stub** (PHASE-6). Absorb B2's carried residuals here: pass a **tz-aware `now`** into `record_access` (else uncaught TypeError); define the signature/`kid` header names; decide NORMAL-tier `request_id` dedup.
- **Gotchas / landmines:**
  - Worktree env: `/home/anti/Tools/EYENET/.venv/bin/python -m ...` from worktree dir (cwd-shadowing). See `feedback_worktree_venv_cwd_shadowing`.
  - **`load_ed25519_public_key` is the ONLY safe way to accept an external Ed25519 pubkey** — never `Ed25519PublicKey.from_public_bytes` directly (it accepts small-order/non-canonical points). Reuse it anywhere B5+ ingests a client key.
  - Three domain tags now exist and MUST stay distinct: `EYENET-SIG-v1` (file-access request), `EYENET-FAJ-v1` (journal row hash), `EYENET-SIGNING-KEY-CHALLENGE-v1` (registration PoP).
  - This codebase has **no AuditSubject enum** — auth handlers emit **string** event names (matched MFA enroll).
  - LOW residual: orphan minted-but-unconsumed challenges accumulate (60s TTL, unconsumable once expired, small-operator scope) — no reaper. Acceptable; add cleanup if it ever matters.
- **Files to start from:** `eyenet/api/v1/auth/api_register_signing_key.py` + `_signing_key_registration.py` (handler pattern), `eyenet/api/v1/attachments/` (stubs), `eyenet/storage/sqlmodel_repo/file_access.py` (`record_access`), `development/API_PLAN.md §5.6`.

## Open questions for the human (PHASE-5 scoping checkpoint)
- Signature/`kid` HTTP header names (working assumption: `X-Operator-Signature: EYENET-SIG-v1 ed25519=<b64>; kid=<16hex>`).
- NORMAL-tier `request_id` dedup — add `UNIQUE(user_id, sig_request_id)` or accept the 300s in-window replay residual?
- Merge cadence: 4 checkpoint commits un-merged. Merge the series after B3, or sooner?
