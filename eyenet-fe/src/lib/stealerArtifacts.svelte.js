// Per-victim artifact drawer state (v1.3.3 + v1.3.4 backend). Five endpoints:
//   GET /v1/stealer/artifacts                       → card grid
//   GET /v1/stealer/artifacts/{sha}/{folder}        → drawer detail + stat tiles + techniques
//   GET /v1/stealer/artifacts/{sha}/{folder}/files  → Files tab tree
//   GET /v1/stealer/artifacts/{sha}/{folder}/records→ Credentials / System tab rows
//   GET /v1/stealer/artifacts/{sha}/{folder}/domains→ EXTRACTED INDICATORS right panel
// All read:stealer-gated; a 200 with initialized:false on /artifacts means the
// corpus is wired but empty (same pattern as /stealer/stats).
import { apiGet } from './api.js';

export const listCtx = $state({
  items: [],
  pageMeta: null,
  initialized: true,
  loading: false,
  error: null,
  denied: false,
  loaded: false,
  // filter + page state owned by the page; stored here so the drawer close
  // doesn't lose the operator's scroll position.
  page: 1,
  q: '',
});

export async function loadArtifacts({ page = 1, country, affid, hasWallet, hasCorporate } = {}) {
  listCtx.loading = true;
  listCtx.error = null;
  listCtx.denied = false;
  try {
    const params = new URLSearchParams({ page: String(page), limit: '25' });
    if (country) params.set('country', country);
    if (affid) params.set('traffic_affid', affid);
    if (hasWallet !== undefined) params.set('has_wallet', String(hasWallet));
    if (hasCorporate !== undefined) params.set('has_corporate', String(hasCorporate));
    const r = await apiGet(`/v1/stealer/artifacts?${params}`, { auth: true });
    listCtx.initialized = r.initialized !== false;
    listCtx.items = r.items ?? [];
    listCtx.pageMeta = r.page_meta ?? null;
    listCtx.page = page;
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

export const drawerCtx = $state({
  open: false,
  sha: null,
  folder: null,
  detail: null,
  files: [],
  records: [],
  recordsMeta: null,
  domains: [],
  tab: 'overview', // overview | files | credentials | system | audit
  loading: false,
  error: null,
  // right panel SELECTED state: which file row (by rel_path) is picked
  selectedFile: null,
});

export async function openDrawer(sha, folder) {
  drawerCtx.open = true;
  drawerCtx.sha = sha;
  drawerCtx.folder = folder;
  drawerCtx.detail = null;
  drawerCtx.files = [];
  drawerCtx.records = [];
  drawerCtx.domains = [];
  drawerCtx.selectedFile = null;
  drawerCtx.tab = 'overview';
  drawerCtx.loading = true;
  drawerCtx.error = null;
  const encFolder = encodeURIComponent(folder);
  try {
    // Parallel: detail + files + domains are cheap, fire together. Records
    // is paged and loads on-demand when the Credentials tab opens.
    const [detail, files, domains] = await Promise.all([
      apiGet(`/v1/stealer/artifacts/${sha}/${encFolder}`, { auth: true }),
      apiGet(`/v1/stealer/artifacts/${sha}/${encFolder}/files`, { auth: true }),
      apiGet(`/v1/stealer/artifacts/${sha}/${encFolder}/domains`, { auth: true }),
    ]);
    drawerCtx.detail = detail;
    drawerCtx.files = files.items ?? [];
    drawerCtx.domains = domains.items ?? [];
  } catch (e) {
    drawerCtx.error = e.status === 503 ? 'Corpus offline.' : (e.message ?? String(e));
  } finally {
    drawerCtx.loading = false;
  }
}

export function closeDrawer() {
  drawerCtx.open = false;
}

export async function loadRecords({ page = 1, ruleId, family } = {}) {
  if (!drawerCtx.sha || !drawerCtx.folder) return;
  const encFolder = encodeURIComponent(drawerCtx.folder);
  try {
    const params = new URLSearchParams({ page: String(page), limit: '50' });
    if (ruleId) params.set('rule_id', ruleId);
    if (family) params.set('family', family);
    const r = await apiGet(
      `/v1/stealer/artifacts/${drawerCtx.sha}/${encFolder}/records?${params}`,
      { auth: true },
    );
    drawerCtx.records = r.items ?? [];
    drawerCtx.recordsMeta = r.page_meta ?? null;
  } catch (e) {
    drawerCtx.error = e.status === 503 ? 'Corpus offline.' : (e.message ?? String(e));
  }
}

export function pickFile(relPath) {
  drawerCtx.selectedFile = relPath;
}
