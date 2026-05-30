# Stream tokens — the browser SSE fallback (M9.A5)

EYENET streams live attribution events over Server-Sent Events (SSE) at
`/v1/stream/*`. In a browser the SSE client is `EventSource`, and `EventSource`
**cannot set an `Authorization` header** — it can only open a URL. Putting a
long-lived JWT or PAT in that URL would leak it into browser history, server
access logs, and `Referer` headers.

The fix is a **stream token**: a short-lived (≤15 min), narrowly-scoped bearer
the UI mints over a normal authenticated `POST`, then hands to `EventSource` as
a `?token=` query parameter. It is the *only* credential that belongs in a URL.

For non-browser consumers (Prometheus, scripts, server-side pullers) use a
**Personal Access Token** instead — those clients send headers. See
[`PAT_RECIPES.md`](PAT_RECIPES.md).

---

## Properties

| Property            | Value                                                       |
|---------------------|-------------------------------------------------------------|
| Lifetime            | ≤ 15 minutes (`ttl_seconds`, 60–900, default 900)           |
| Transport           | `?token=` query param on `GET /v1/stream/*`                 |
| At rest             | Stateless RS256 JWT (`typ:"stream"`) — **not** stored        |
| Revocation          | Expiry only; ephemeral by design (no denylist)              |
| Capability          | Frozen to the topics it was minted for                      |
| Authority           | Re-resolved live from storage at connect (SSE milestone)    |

A stream token carries `typ:"stream"` and is cryptographically isolated from
the access-token path: it cannot authenticate a normal API request, and an
access token cannot authenticate a stream. Both are rejected with `401`.

## Topics and the scopes they require

A topic is mintable only if the caller currently holds the matching `stream:*`
scope. Requesting a topic you lack returns `403`.

| Topic                   | Required scope     | ADMIN | ANALYST | VIEWER |
|-------------------------|--------------------|:-----:|:-------:|:------:|
| `attribution.linkage`   | `stream:linkages`  |  ✅   |   ✅    |   —    |
| `attribution.persona`   | `stream:personas`  |  ✅   |   ✅    |   —    |
| `eyenet.audit`          | `stream:audit`     |  ✅   |   —     |   —    |
| `eyenet.control`        | `stream:control`   |  ✅   |   —     |   —    |

## Browser flow

```js
// 1. Mint a stream token over the authenticated session (Authorization header).
const res = await fetch('/v1/auth/stream-token', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ topics: ['attribution.linkage', 'attribution.persona'] }),
});
const { stream_token, expires_at } = await res.json();

// 2. Hand it to EventSource as a query param (the only place a token in a URL
//    is acceptable — it expires in minutes and is scoped to these topics).
const es = new EventSource(`/v1/stream/all?token=${encodeURIComponent(stream_token)}`);
es.onmessage = (e) => { /* … */ };

// 3. The token is short-lived. Re-mint shortly before `expires_at` and
//    reconnect. Do NOT persist it (no localStorage) — keep it in memory and
//    treat it as disposable.
```

`Last-Event-ID` resumption (gap replay after a reconnect) is handled by the SSE
delivery layer, independent of the token.

## Operational notes

- **Don't store stream tokens.** They are disposable; re-mint on expiry. A
  leaked one self-heals in ≤15 minutes, which is exactly why there is no
  revocation endpoint.
- **Signing key.** Stream tokens are signed with the same RSA-4096 keypair as
  access tokens (`<data_dir>/jwt/signing_key.pem`). Rotating or losing that key
  invalidates stream tokens too — same backup story as the rest of `jwt/`
  (see [`MFA_OPS.md`](MFA_OPS.md) §1).
- **Live authority.** A token frozen to its topics still can't outrun a revoked
  role: the SSE endpoint re-resolves `stream:*` scopes from storage at connect
  time, so demoting a user cuts their stream within the cache TTL even on a
  still-valid token.

See `development/API_PLAN.md` §6.4.2 for the protocol-level spec.
