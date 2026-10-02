// Personal Access Token (PAT) workspace — SYSTEM / Auth & tokens.
// Mint/list/revoke a caller-owned PAT via the real API (the page was a stub
// fed by $lib/data.js). The scrape token for the observability stack is just a
// PAT scoped to [read:metrics]; the secret is shown ONCE at mint time.
import { apiDelete, apiGet, apiPost } from './api.js';

const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');

function mapToken(t) {
  const expired = t.expires_at && new Date(t.expires_at) < new Date();
  return {
    id: t.token_id, // stable id for selection + revoke
    prefix: t.prefix,
    label: t.name || '—',
    scopes: (t.scopes ?? []).join(' '),
    last_used: shortTs(t.last_used_at),
    status: expired ? 'expired' : 'active'
  };
}

export const tokenCtx = $state({ list: [], loaded: false, error: null, busy: false, error_msg: null });
// The one-time full secret, surfaced right after a successful mint. Cleared when
// the operator dismisses it — never re-fetchable.
export const mintResult = $state({ secret: null, label: null });

export async function loadTokens() {
  try {
    const all = [];
    let cursor = null;
    do {
      const qs = new URLSearchParams({ limit: '200' });
      if (cursor) qs.set('cursor', cursor);
      const page = await apiGet(`/v1/auth/tokens?${qs}`, { auth: true });
      all.push(...(page.items ?? []));
      cursor = page.next_cursor ?? null;
    } while (cursor);
    tokenCtx.list = all.map(mapToken);
    tokenCtx.loaded = true;
    tokenCtx.error = null;
  } catch (e) {
    tokenCtx.error = e.message ?? String(e);
    tokenCtx.loaded = true;
  }
}

// Mint a PAT. `scopes` must be a subset of the caller's held scopes (the server
// re-enforces this). On success stashes the one-time secret in `mintResult`.
export async function mintToken({ name, scopes, expiresAt = null }) {
  tokenCtx.busy = true;
  tokenCtx.error_msg = null;
  try {
    const body = { name, scopes };
    if (expiresAt) body.expires_at = expiresAt;
    const r = await apiPost('/v1/auth/tokens', body, { auth: true });
    mintResult.secret = r.secret;
    mintResult.label = r.name;
    await loadTokens();
    return true;
  } catch (e) {
    tokenCtx.error_msg = `Mint failed: ${e.message ?? e}`;
    return false;
  } finally {
    tokenCtx.busy = false;
  }
}

export function clearMintResult() {
  mintResult.secret = null;
  mintResult.label = null;
}

export async function revokeToken(tokenId) {
  tokenCtx.busy = true;
  tokenCtx.error_msg = null;
  try {
    await apiDelete(`/v1/auth/tokens/${tokenId}`, { auth: true });
    await loadTokens();
    return true;
  } catch (e) {
    tokenCtx.error_msg = `Revoke failed: ${e.message ?? e}`;
    return false;
  } finally {
    tokenCtx.busy = false;
  }
}
