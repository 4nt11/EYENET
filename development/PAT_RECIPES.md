# Personal Access Token operator recipes (M9.A4)

Personal Access Tokens (PATs) are non-interactive bearer credentials for
automation — Prometheus scraping, read-only feed pullers, CI jobs — that
must authenticate to the EYENET API without a human JWT login. A PAT
presents as a normal `Authorization: Bearer <token>` and resolves to the
same principal a JWT would, with one difference: its scopes are **frozen at
mint** and it is revoked by deleting the token, never by logout.

---

## 1. The token format

```
eyenet_pat_<22-char-prefix>_<32-char-secret>
```

- The full string is shown **exactly once**, in the `secret` field of the
  mint response. It is never re-displayed and cannot be recovered — if lost,
  revoke and re-mint.
- The `prefix` is stored in plaintext and shown in listings so you can tell
  tokens apart. The secret is stored only as `HMAC-SHA256(pat_pepper, secret)`
  (see `development/MFA_OPS.md` §1 for the pepper).

---

## 2. Scope rules

- A PAT may carry **any scope the minting user currently holds, and no more**
  (`requested ⊆ your effective scopes`). Requesting a scope you don't hold —
  or a scope that doesn't exist — fails the mint with `422`.
- Scopes are **frozen at mint**: the token keeps exactly the scopes captured
  then, until revoked. (A later role change does not retroactively widen or
  narrow an existing PAT — revoke and re-mint to change a token's authority.)
- **Least privilege:** mint a PAT with only the scopes the job needs. A
  metrics scraper needs `read:metrics` and nothing else.

---

## 3. Least-privilege Prometheus scrape recipe

Run Prometheus under a dedicated service-account user that holds **only**
`read:metrics`, mint a PAT for it, and point the scrape job's bearer auth at
that PAT. (The `/v1/metrics` endpoint itself lands in M9.I3; this recipe is
ready for it.)

### 3.1 Mint the token

Authenticate as the service account (or any user that holds `read:metrics`),
then:

```bash
# $ACCESS is a current access JWT for the minting user.
curl -sS -X POST https://eyenet.example.internal/v1/auth/tokens \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -d '{"name": "prometheus-scrape", "scopes": ["read:metrics"]}'
```

Response (`201`) — copy `secret` now, it is shown once:

```json
{
  "token_id": "0192...",
  "name": "prometheus-scrape",
  "prefix": "AbCdEfGhIjKlMnOpQrStUv",
  "scopes": ["read:metrics"],
  "secret": "eyenet_pat_AbCdEfGhIjKlMnOpQrStUv_0123456789abcdef0123456789abcd",
  "created_at": "2026-05-30T12:00:00Z",
  "expires_at": null
}
```

### 3.2 Configure the scrape job

`prometheus.yml`:

```yaml
scrape_configs:
  - job_name: eyenet
    scheme: https
    metrics_path: /v1/metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/eyenet_pat   # contains the full eyenet_pat_... string
    static_configs:
      - targets: ["eyenet.example.internal:443"]
```

Store the token in a file (`credentials_file`) rather than inline
`credentials:` so it stays out of the rendered config and process args:

```bash
umask 077
printf '%s' 'eyenet_pat_AbCdEfGhIjKlMnOpQrStUv_0123456789abcdef0123456789abcd' \
  > /etc/prometheus/eyenet_pat
```

### 3.3 List and revoke

```bash
# List your tokens (secrets are never returned):
curl -sS https://eyenet.example.internal/v1/auth/tokens \
  -H "Authorization: Bearer $ACCESS"

# Revoke immediately — the token stops authenticating on the next request:
curl -sS -X DELETE https://eyenet.example.internal/v1/auth/tokens/$TOKEN_ID \
  -H "Authorization: Bearer $ACCESS"
```

A token holder can revoke their own tokens; a user with `admin:tokens` can
revoke anyone's. Attempting to revoke a token you neither own nor have
`admin:tokens` for returns `404` (no existence oracle).

---

## 4. Operational notes

- **Idempotency:** the mint endpoint accepts an `Idempotency-Key` header,
  recorded in the audit trail for retry correlation. It is **not** a replay
  guard — each mint produces a distinct secret. Don't retry a mint blindly;
  list first if a network error leaves the outcome uncertain.
- **Expiry:** pass `expires_at` to time-box a token. Omit it for a
  non-expiring credential (revoke to end its life).
- **`last_used_at`** is updated best-effort, coarsened to ~60s, so a
  high-frequency scrape loop is not a write per request.
- **Audit:** mint emits `eyenet.audit.auth.token.minted`, revoke emits
  `eyenet.audit.auth.token.revoked` (both never carry the secret).

---

## 5. Losing the pepper — disaster recovery

`pat_pepper` (`<data_dir>/jwt/pat_pepper`) keys every PAT's at-rest hash.
If it is lost or rotated, **every existing PAT becomes unverifiable** — each
will fail auth with a flat `401`. Recovery is to re-mint: issue fresh tokens
and update each automation's `credentials_file`. There is no way to recover
the old secrets (that is the point — the pepper lives off-database). Back it
up with the same cadence as `mfa_key` and the JWT signing key
(`development/MFA_OPS.md` §2). Pepper rotation is operator-manual and is not
exposed as a CLI in A4.

---

## 6. Cross-references

- `eyenet/api/auth/_pat.py` — mint / parse / HMAC / pepper loader
- `eyenet/api/deps.py` — `get_current_user` PAT resolution path
- `eyenet/api/v1/auth/api_mint_token.py` / `api_list_tokens.py` / `api_revoke_token.py`
- `development/MFA_OPS.md` §1–§2 — key material + backup story
- `development/API_PLAN.md` §4.3 — PAT spec source of truth
