// Domain View client. Hits /v1/stealer/by-domain/{domain}/* (all read:stealer-gated).
// One Svelte-5 state object per endpoint, loaded on demand so navigating between
// tabs does not re-fetch what's already in hand. The summary endpoint fires on
// landing because the hero is always visible.
import { apiGet } from './api.js';

// Each ctx carries a `key` -- the signature of the last-served params.
// A loader call whose params hash to the same key is a no-op: the ctx
// IS the cache, so flipping back to a tab you already loaded is free.
// Lives only for the SPA session; a hard reload wipes it, which is the
// escape hatch for operators who want to see fresh server state.
export const summaryCtx = $state({
  domain: null,            // canonical form the backend resolved to
  raw: null,               // what the user typed
  summary: null,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainSummary(raw) {
  if (summaryCtx.key === raw && summaryCtx.loaded && !summaryCtx.error) return;
  summaryCtx.raw = raw;
  summaryCtx.loading = true;
  summaryCtx.error = null;
  summaryCtx.denied = false;
  try {
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/summary`, { auth: true });
    summaryCtx.summary = data;
    summaryCtx.domain = data?.canonical_domain ?? raw;
    summaryCtx.key = raw;
  } catch (e) {
    if (e.status === 403) summaryCtx.denied = true;
    else if (e.status === 503) summaryCtx.error = 'Corpus offline (the stealer pipeline is not running).';
    else summaryCtx.error = e.message ?? String(e);
    summaryCtx.summary = null;
  } finally {
    summaryCtx.loading = false;
    summaryCtx.loaded = true;
  }
}

export const subdomainsCtx = $state({
  items: [],
  total: 0,
  limit: 100,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainSubdomains(raw, { limit = 100 } = {}) {
  const key = `${raw}:${limit}`;
  if (subdomainsCtx.key === key && subdomainsCtx.loaded && !subdomainsCtx.error) return;
  subdomainsCtx.loading = true;
  subdomainsCtx.error = null;
  subdomainsCtx.denied = false;
  subdomainsCtx.limit = limit;
  try {
    const q = new URLSearchParams({ limit: String(limit) });
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/subdomains?${q}`, { auth: true });
    subdomainsCtx.items = data?.items ?? [];
    subdomainsCtx.total = data?.total ?? 0;
    subdomainsCtx.key = key;
  } catch (e) {
    if (e.status === 403) subdomainsCtx.denied = true;
    else if (e.status === 503) subdomainsCtx.error = 'Corpus offline.';
    else subdomainsCtx.error = e.message ?? String(e);
    subdomainsCtx.items = [];
  } finally {
    subdomainsCtx.loading = false;
    subdomainsCtx.loaded = true;
  }
}

export const cookiesCtx = $state({
  items: [],
  total: 0,
  pages: 0,
  page: 1,
  limit: 50,
  live_only: false,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

// Cookies needs a multi-slot cache because the Live-only toggle flips the
// key on the same (domain, page, limit): a single-slot ctx.key gets
// overwritten and the operator pays the network round-trip to re-see a
// page they already saw. Scoped to this loader; all other tabs stay
// single-slot since nothing else toggles a filter without re-paginating.
const _cookiesCache = new Map();

export async function loadDomainCookies(raw, { page = 1, limit = 50, live_only = false } = {}) {
  const key = `${raw}:${page}:${limit}:${live_only}`;
  if (cookiesCtx.key === key && cookiesCtx.loaded && !cookiesCtx.error) return;
  const hit = _cookiesCache.get(key);
  if (hit) {
    cookiesCtx.items = hit.items;
    cookiesCtx.total = hit.total;
    cookiesCtx.pages = hit.pages;
    cookiesCtx.page = page;
    cookiesCtx.limit = limit;
    cookiesCtx.live_only = live_only;
    cookiesCtx.loaded = true;
    cookiesCtx.error = null;
    cookiesCtx.denied = false;
    cookiesCtx.key = key;
    return;
  }
  cookiesCtx.loading = true;
  cookiesCtx.error = null;
  cookiesCtx.denied = false;
  cookiesCtx.page = page;
  cookiesCtx.limit = limit;
  cookiesCtx.live_only = live_only;
  try {
    const q = new URLSearchParams({ page: String(page), limit: String(limit), live_only: String(live_only) });
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/cookies?${q}`, { auth: true });
    cookiesCtx.items = data?.items ?? [];
    cookiesCtx.total = data?.total ?? 0;
    cookiesCtx.pages = data?.pages ?? 0;
    cookiesCtx.key = key;
    _cookiesCache.set(key, {
      items: cookiesCtx.items,
      total: cookiesCtx.total,
      pages: cookiesCtx.pages,
    });
  } catch (e) {
    if (e.status === 403) cookiesCtx.denied = true;
    else if (e.status === 503) cookiesCtx.error = 'Corpus offline.';
    else cookiesCtx.error = e.message ?? String(e);
    cookiesCtx.items = [];
  } finally {
    cookiesCtx.loading = false;
    cookiesCtx.loaded = true;
  }
}

export const victimsCtx = $state({
  items: [],
  total: 0,
  pages: 0,
  page: 1,
  limit: 50,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainVictims(raw, { page = 1, limit = 50 } = {}) {
  const key = `${raw}:${page}:${limit}`;
  if (victimsCtx.key === key && victimsCtx.loaded && !victimsCtx.error) return;
  victimsCtx.loading = true;
  victimsCtx.error = null;
  victimsCtx.denied = false;
  victimsCtx.page = page;
  victimsCtx.limit = limit;
  try {
    const q = new URLSearchParams({ page: String(page), limit: String(limit) });
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/victims?${q}`, { auth: true });
    victimsCtx.items = data?.items ?? [];
    victimsCtx.total = data?.total ?? 0;
    victimsCtx.pages = data?.pages ?? 0;
    victimsCtx.key = key;
  } catch (e) {
    if (e.status === 403) victimsCtx.denied = true;
    else if (e.status === 503) victimsCtx.error = 'Corpus offline.';
    else victimsCtx.error = e.message ?? String(e);
    victimsCtx.items = [];
  } finally {
    victimsCtx.loading = false;
    victimsCtx.loaded = true;
  }
}

export const autofillsCtx = $state({
  items: [],
  total: 0,
  pages: 0,
  page: 1,
  limit: 50,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainAutofills(raw, { page = 1, limit = 50 } = {}) {
  const key = `${raw}:${page}:${limit}`;
  if (autofillsCtx.key === key && autofillsCtx.loaded && !autofillsCtx.error) return;
  autofillsCtx.loading = true;
  autofillsCtx.error = null;
  autofillsCtx.denied = false;
  autofillsCtx.page = page;
  autofillsCtx.limit = limit;
  try {
    const q = new URLSearchParams({ page: String(page), limit: String(limit) });
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/autofills?${q}`, { auth: true });
    autofillsCtx.items = data?.items ?? [];
    autofillsCtx.total = data?.total ?? 0;
    autofillsCtx.pages = data?.pages ?? 0;
    autofillsCtx.key = key;
  } catch (e) {
    if (e.status === 403) autofillsCtx.denied = true;
    else if (e.status === 503) autofillsCtx.error = 'Corpus offline.';
    else autofillsCtx.error = e.message ?? String(e);
    autofillsCtx.items = [];
  } finally {
    autofillsCtx.loading = false;
    autofillsCtx.loaded = true;
  }
}

export const historyCtx = $state({
  items: [],
  total: 0,
  pages: 0,
  page: 1,
  limit: 50,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainHistory(raw, { page = 1, limit = 50 } = {}) {
  const key = `${raw}:${page}:${limit}`;
  if (historyCtx.key === key && historyCtx.loaded && !historyCtx.error) return;
  historyCtx.loading = true;
  historyCtx.error = null;
  historyCtx.denied = false;
  historyCtx.page = page;
  historyCtx.limit = limit;
  try {
    const q = new URLSearchParams({ page: String(page), limit: String(limit) });
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/history?${q}`, { auth: true });
    historyCtx.items = data?.items ?? [];
    historyCtx.total = data?.total ?? 0;
    historyCtx.pages = data?.pages ?? 0;
    historyCtx.key = key;
  } catch (e) {
    if (e.status === 403) historyCtx.denied = true;
    else if (e.status === 503) historyCtx.error = 'Corpus offline.';
    else historyCtx.error = e.message ?? String(e);
    historyCtx.items = [];
  } finally {
    historyCtx.loading = false;
    historyCtx.loaded = true;
  }
}

export const localstorageCtx = $state({
  items: [],
  total: 0,
  pages: 0,
  page: 1,
  limit: 50,
  live_count: 0,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainLocalStorage(raw, { page = 1, limit = 50 } = {}) {
  const key = `${raw}:${page}:${limit}`;
  if (localstorageCtx.key === key && localstorageCtx.loaded && !localstorageCtx.error) return;
  localstorageCtx.loading = true;
  localstorageCtx.error = null;
  localstorageCtx.denied = false;
  localstorageCtx.page = page;
  localstorageCtx.limit = limit;
  try {
    const q = new URLSearchParams({ page: String(page), limit: String(limit) });
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/localstorage?${q}`, { auth: true });
    localstorageCtx.items = data?.items ?? [];
    localstorageCtx.total = data?.total ?? 0;
    localstorageCtx.pages = data?.pages ?? 0;
    localstorageCtx.live_count = data?.live_count ?? 0;
    localstorageCtx.key = key;
  } catch (e) {
    if (e.status === 403) localstorageCtx.denied = true;
    else if (e.status === 503) localstorageCtx.error = 'Corpus offline.';
    else localstorageCtx.error = e.message ?? String(e);
    localstorageCtx.items = [];
  } finally {
    localstorageCtx.loading = false;
    localstorageCtx.loaded = true;
  }
}

export const antivirusesCtx = $state({
  items: [],
  domain_total_victims: 0,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainAntiviruses(raw) {
  const key = raw;
  if (antivirusesCtx.key === key && antivirusesCtx.loaded && !antivirusesCtx.error) return;
  antivirusesCtx.loading = true;
  antivirusesCtx.error = null;
  antivirusesCtx.denied = false;
  try {
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/antiviruses`, { auth: true });
    antivirusesCtx.items = data?.items ?? [];
    antivirusesCtx.domain_total_victims = data?.domain_total_victims ?? 0;
    antivirusesCtx.key = key;
  } catch (e) {
    if (e.status === 403) antivirusesCtx.denied = true;
    else if (e.status === 503) antivirusesCtx.error = 'Corpus offline.';
    else antivirusesCtx.error = e.message ?? String(e);
    antivirusesCtx.items = [];
  } finally {
    antivirusesCtx.loading = false;
    antivirusesCtx.loaded = true;
  }
}

export const samplesCtx = $state({
  items: [],
  domain_total_victims: 0,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainSamples(raw, { limit = 50 } = {}) {
  const key = `${raw}:${limit}`;
  if (samplesCtx.key === key && samplesCtx.loaded && !samplesCtx.error) return;
  samplesCtx.loading = true;
  samplesCtx.error = null;
  samplesCtx.denied = false;
  try {
    const q = new URLSearchParams({ limit: String(limit) });
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/samples?${q}`, { auth: true });
    samplesCtx.items = data?.items ?? [];
    samplesCtx.domain_total_victims = data?.domain_total_victims ?? 0;
    samplesCtx.key = key;
  } catch (e) {
    if (e.status === 403) samplesCtx.denied = true;
    else if (e.status === 503) samplesCtx.error = 'Corpus offline.';
    else samplesCtx.error = e.message ?? String(e);
    samplesCtx.items = [];
  } finally {
    samplesCtx.loading = false;
    samplesCtx.loaded = true;
  }
}

// Per-sample drilldown. Keyed by (domain, md5); cached across tab
// close/reopen so re-expanding the same row is instant.
const _sampleDetailCache = new Map();
export async function loadSampleDetail(raw, loaderMd5) {
  const key = `${raw}:${loaderMd5}`;
  const hit = _sampleDetailCache.get(key);
  if (hit) return hit;
  const data = await apiGet(
    `/v1/stealer/by-domain/${encodeURIComponent(raw)}/samples/${encodeURIComponent(loaderMd5)}`,
    { auth: true },
  );
  _sampleDetailCache.set(key, data);
  return data;
}

export const credentialsCtx = $state({
  items: [],
  total: 0,
  pages: 0,
  page: 1,
  limit: 50,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  key: null,
});

export async function loadDomainCredentials(raw, { page = 1, limit = 50 } = {}) {
  const key = `${raw}:${page}:${limit}`;
  if (credentialsCtx.key === key && credentialsCtx.loaded && !credentialsCtx.error) return;
  credentialsCtx.loading = true;
  credentialsCtx.error = null;
  credentialsCtx.denied = false;
  credentialsCtx.page = page;
  credentialsCtx.limit = limit;
  try {
    const q = new URLSearchParams({ page: String(page), limit: String(limit) });
    const data = await apiGet(`/v1/stealer/by-domain/${encodeURIComponent(raw)}/credentials?${q}`, { auth: true });
    credentialsCtx.items = data?.items ?? [];
    credentialsCtx.total = data?.total ?? 0;
    credentialsCtx.pages = data?.pages ?? 0;
    credentialsCtx.key = key;
  } catch (e) {
    if (e.status === 403) credentialsCtx.denied = true;
    else if (e.status === 503) credentialsCtx.error = 'Corpus offline.';
    else credentialsCtx.error = e.message ?? String(e);
    credentialsCtx.items = [];
  } finally {
    credentialsCtx.loading = false;
    credentialsCtx.loaded = true;
  }
}
