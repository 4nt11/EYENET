# MFA operator runbook (M9.A3)

This file is the durable operator-facing companion to API_PLAN §M9.A3.
It covers everything outside the API surface: key material, backups,
lockout recovery, and the manual key-rotation procedure.

If you're reading this because something is wrong, jump to §4 (Lockout
recovery) or §5 (Lost mfa_key — disaster recovery).

---

## 1. Key material on disk

EYENET stores ONE Fernet key for TOTP-secret encryption at rest:

```
<data_dir>/jwt/mfa_key   mode 0600, owner = service account
```

This file is auto-generated on first call to `eyenet.api.auth.load_mfa_key`
(which the app factory triggers at startup). The file lives in the same
directory as the JWT signing keypair (`signing_key.pem`,
`verifying_key.pem`), so backing up `<data_dir>/jwt/` covers both.

The key is **symmetric** (AES-128-CBC + HMAC-SHA256 in the Fernet
construction). It encrypts the per-user TOTP secret stored in
`system_user_credential.mfa_secret_encrypted`. The plaintext TOTP secret
never touches storage; it only exists in-process during enrollment and
login-verify.

---

## 2. Backups

Treat `<data_dir>/jwt/mfa_key` with the same cadence as the JWT signing
key. Recommended:

- Daily snapshot of `<data_dir>/jwt/` to operator-controlled cold storage.
- Off-host copy in the same secure store that holds the JWT keypair.
- File-system-level integrity (immutable backups, audit-grade access logs
  on the backup target).

**Do not check `mfa_key` into source control.** EYENET's `.gitignore`
covers `data/*` by default; verify before deploying.

---

## 3. Audit subjects emitted by the MFA flow

The full set, all under `eyenet.audit.auth.mfa.*`:

| Subject              | Trigger                                                       |
|----------------------|---------------------------------------------------------------|
| `enrolled`           | `POST /v1/auth/mfa/verify-enroll` success                     |
| `enroll_failed`      | `POST /v1/auth/mfa/verify-enroll` rejected (bad code)         |
| `challenge_issued`   | `POST /v1/auth/login` short-circuited to MFA prompt           |
| `verified`           | `POST /v1/auth/login/verify` success                          |
| `verify_failed`      | `POST /v1/auth/login/verify` bad code (one row per attempt)   |
| `replay_attempt`     | `POST /v1/auth/login/verify` against a consumed challenge     |
| `locked_out`         | `POST /v1/auth/login/verify` while the user is in 5/15 lockout |
| `disabled`           | `DELETE /v1/auth/mfa` success                                 |
| `disable_failed`     | `DELETE /v1/auth/mfa` rejected (wrong password)               |
| `unlocked`           | `eyenet user unlock-mfa <user>` CLI run                       |

All rows carry `system_user_id` and `subject_id` set to the user being
acted on. Lockout decisions are NOT visible to the wire client (401 with
the standard "authentication failed" body); only the audit log shows
lockout vs. plain bad-code.

---

## 4. Lockout recovery

Lockout policy: **5 failed `/v1/auth/login/verify` attempts within 15
minutes** locks `/login/verify` for that user. The lockout window slides
from the most recent failed row — a steady drip of guesses keeps the
user locked indefinitely.

Two ways to recover:

### 4a. Wait it out (no operator action)

After 15 minutes of no failed attempts, the window query returns 0 and
the user can verify normally.

### 4b. Operator unlock

If the legitimate user needs immediate access (operations site visit at
2am, the brute-force traffic was hostile, etc.), an operator runs:

```bash
eyenet user unlock-mfa <username>
```

This zeroes `failed_attempts` on every `mfa_challenge` row for that user
inside the active 15-minute window and emits `mfa.unlocked` to the audit
chain. It does NOT reset the enrolled TOTP secret — the user still
authenticates with the same authenticator-app code.

If the user has **lost their authenticator device**, use the A6 command
`eyenet user reset-mfa <username>` (when A6 ships) — different semantics:
that one wipes the encrypted secret entirely and forces re-enrollment.

---

## 5. Lost `mfa_key` — disaster recovery

If `<data_dir>/jwt/mfa_key` is deleted, corrupted, or replaced without a
prior backup, every existing `mfa_secret_encrypted` becomes
**unrecoverable**. The login-verify handler will return 401 to every
enrolled user (audit: `mfa_secret_unreadable` reason on the AuthError).

Recovery procedure:

1. Restore `mfa_key` from the most recent good backup. Re-test the login
   flow with a known-enrolled test user.
2. If no backup exists: every MFA-enrolled user must re-enroll. The A6
   command `eyenet user reset-mfa --all` will be the bulk path; until A6
   ships, the manual procedure is:

   ```sql
   UPDATE system_user_credential SET mfa_secret_encrypted = NULL;
   ```

   (Run via a SQLite session against the main DB, then bounce the API
   service so cached credentials are reloaded.) Then notify users to
   re-enroll at `/v1/auth/mfa/enroll`.

---

## 6. Key rotation (manual)

EYENET does NOT ship automated MFA-key rotation in M9.A3 — the operator
runs a two-step procedure during a maintenance window:

1. Generate the new key separately:

   ```bash
   python -c "from cryptography.fernet import Fernet; \
              import pathlib; \
              pathlib.Path('/tmp/mfa_key.new').write_bytes(Fernet.generate_key())"
   chmod 0600 /tmp/mfa_key.new
   ```

2. Run an offline re-encryption script (operator-owned; not bundled in
   A3) that:
   - Reads every `system_user_credential` row with a non-NULL
     `mfa_secret_encrypted`.
   - Decrypts with the current key, re-encrypts with the new key.
   - Updates each row in place.
3. Stop the API service.
4. Atomically replace `<data_dir>/jwt/mfa_key` with the new key.
5. Restart. Verify a known-enrolled test user can still complete the
   login → verify flow.

Rotation tooling (CLI-driven, online-safe with read-old/write-new dual
key support) lands with the broader key-management slice — out of scope
for A3.

---

## 7. TOTP parameters — why these defaults

| Parameter      | Value      | Rationale                                                 |
|----------------|-----------|------------------------------------------------------------|
| Algorithm      | HMAC-SHA-1 | Universal authenticator-app compatibility (RFC 6238)       |
| Digits         | 6          | Same — every authenticator app supports 6 digits           |
| Step           | 30 s       | Same                                                       |
| Tolerance      | ±1 step    | Accommodates clock drift per RFC 6238 §5.2                 |
| Secret bytes   | 20 (160 b) | RFC 4226 §4 recommended floor                              |

Changing any of these silently invalidates every enrolled user's
authenticator. If a rotation is ever needed, it ships as a coordinated
re-enrollment migration, not a code change.

---

## 8. Cross-references

- `eyenet/api/auth/_mfa.py` — TOTP helpers
- `eyenet/api/auth/_mfa_key.py` — Fernet load/encrypt/decrypt
- `eyenet/api/v1/auth/api_login_verify.py` — verify-flow contract
- `eyenet/cli/user.py` — `unlock-mfa` operator command
- `development/API_PLAN.md` §M9.A3 — spec source of truth
- `CLAUDE.md` §6 — worktree-based atomic-cutover pattern that landed A3
