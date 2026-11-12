// ULP corpus dashboard state. Stats (totals + distributions for the charts) from
// GET /v1/stealer/stats, credential search from GET /v1/stealer/search — both
// read:stealer-gated (a 403 => the operator lacks the clearance grant). Svelte 5 runes.
import { apiGet } from './api.js';

// `uninitialized` = the backend returned 200 with initialized:false, meaning the
// ClickHouse `stealer.creds` table does not exist yet (no stealer channel has
// been ingested). Distinct from `error` (CH actually unreachable) so the page
// can render a "set up a stealer channel" shortcut instead of an outage banner.
export const statsCtx = $state({ stats: null, loading: false, error: null, denied: false, loaded: false, uninitialized: false });

export async function loadStealerStats() {
  statsCtx.loading = true;
  statsCtx.error = null;
  statsCtx.denied = false;
  statsCtx.uninitialized = false;
  try {
    statsCtx.stats = await apiGet('/v1/stealer/stats', { auth: true });
    statsCtx.uninitialized = statsCtx.stats?.initialized === false;
  } catch (e) {
    if (e.status === 403) statsCtx.denied = true;
    else if (e.status === 503) statsCtx.error = 'Corpus offline (the stealer pipeline is not running).';
    else statsCtx.error = e.message ?? String(e);
    statsCtx.stats = null;
  } finally {
    statsCtx.loading = false;
    statsCtx.loaded = true;
  }
}

export const searchCtx = $state({ items: [], loading: false, error: null, ran: false });

export async function searchStealer(host) {
  searchCtx.loading = true;
  searchCtx.error = null;
  searchCtx.ran = true;
  try {
    const params = new URLSearchParams({ limit: '200' });
    if (host && host.trim()) params.set('host', host.trim());
    const r = await apiGet(`/v1/stealer/search?${params}`, { auth: true });
    searchCtx.items = r.items;
  } catch (e) {
    searchCtx.error = e.status === 503 ? 'Corpus offline.' : (e.message ?? String(e));
    searchCtx.items = [];
  } finally {
    searchCtx.loading = false;
  }
}
