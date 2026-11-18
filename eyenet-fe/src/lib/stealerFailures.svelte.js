// Parse-failures workbench state. Backs /tuning/stealer/failures.
// Two endpoints (read:stealer):
//   GET /v1/stealer/failures?page&limit&filename?&heuristic_kind?
//   GET /v1/stealer/failures/{shape_sig:path}/samples?limit
// A failure = a file that matched a path_glob but 0 extracted_records were
// emitted. Shape fingerprint groups them so the operator fixes one shape at
// a time, not one file at a time.
import { apiGet } from './api.js';

export const listCtx = $state({
  items: [],
  pageMeta: null,
  initialized: true,
  loading: false,
  loaded: false,
  error: null,
  denied: false,
  page: 1,
  filters: { filename: '', heuristic_kind: '' },
});

export async function loadFailures({ page = 1, filename, heuristic_kind } = {}) {
  listCtx.loading = true;
  listCtx.error = null;
  listCtx.denied = false;
  try {
    const params = new URLSearchParams({ page: String(page), limit: '25' });
    const fn = filename ?? listCtx.filters.filename;
    const hk = heuristic_kind ?? listCtx.filters.heuristic_kind;
    if (fn) params.set('filename', fn);
    if (hk) params.set('heuristic_kind', hk);
    const r = await apiGet(`/v1/stealer/failures?${params}`, { auth: true });
    listCtx.initialized = r.initialized !== false;
    listCtx.items = r.items ?? [];
    listCtx.pageMeta = r.page_meta ?? null;
    listCtx.page = page;
    listCtx.filters = { filename: fn ?? '', heuristic_kind: hk ?? '' };
  } catch (e) {
    if (e.status === 403) listCtx.denied = true;
    else listCtx.error = e.message ?? String(e);
    listCtx.items = [];
    listCtx.pageMeta = null;
  } finally {
    listCtx.loading = false;
    listCtx.loaded = true;
  }
}

export const statsCtx = $state({
  initialized: true,
  total_files: 0,
  parsed_files: 0,
  coverage_pct: 0,
  fail_files: 0,
  shape_buckets: 0,
  crash_files: 0,
  loading: false,
  loaded: false,
  error: null,
});

export async function loadStats() {
  statsCtx.loading = true;
  statsCtx.error = null;
  try {
    const r = await apiGet('/v1/stealer/failures/stats', { auth: true });
    Object.assign(statsCtx, r);
    statsCtx.initialized = r.initialized !== false;
  } catch (e) {
    statsCtx.error = e.message ?? String(e);
  } finally {
    statsCtx.loading = false;
    statsCtx.loaded = true;
  }
}

export const samplesCtx = $state({
  // shape_sig -> { loading, error, items }
  bySig: {},
});

export async function loadSamples(shape_sig, { limit = 50 } = {}) {
  const cur = samplesCtx.bySig[shape_sig];
  if (cur && (cur.loading || cur.items)) return;
  samplesCtx.bySig[shape_sig] = { loading: true, error: null, items: null };
  try {
    const enc = shape_sig.split('/').map(encodeURIComponent).join('/');
    const r = await apiGet(
      `/v1/stealer/failures/${enc}/samples?limit=${limit}`,
      { auth: true },
    );
    samplesCtx.bySig[shape_sig] = { loading: false, error: null, items: r.items ?? [] };
  } catch (e) {
    samplesCtx.bySig[shape_sig] = {
      loading: false,
      error: e.message ?? String(e),
      items: [],
    };
  }
}
