// Sources workspace state. The list comes from GET /v1/sources (read:sources);
// selecting a source fetches GET /v1/sources/{id} for its inlined active
// domains + resolved-artifact count. Svelte 5 runes in a module = universal
// reactive state, same shape as case.svelte.js.
import { apiGet } from './api.js';

const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '');

// SourceSummary → the flat shape the table/detail consume.
function mapSource(s) {
  return {
    id: s.source_id,
    platform: s.kind,
    name: s.display_name,
    domainCount: s.active_domain_count ?? 0,
    canonicalUrl: s.canonical_url ?? null,
    created: shortTs(s.created_at)
  };
}

export const sourceCtx = $state({ list: [], loaded: false, error: null });

export async function loadSources() {
  try {
    const page = await apiGet('/v1/sources', { auth: true });
    sourceCtx.list = page.items.map(mapSource);
    sourceCtx.error = null;
  } catch (e) {
    sourceCtx.error = e.message ?? String(e);
    sourceCtx.list = [];
  } finally {
    sourceCtx.loaded = true;
  }
}

// Selected-source detail. domains are the inlined SourceDomainView rows; we
// keep only the active ones (removed_at == null) and surface each row's
// `pattern` as its display string.
export const sourceView = $state({
  sourceId: null,
  domains: [],
  resolvedCount: 0,
  loading: false,
  error: null
});

// Monotonic token so a slow detail fetch can't land after a newer selection
// and show the wrong source's domains.
let detailSeq = 0;

export async function loadSourceDetail(sourceId) {
  const mine = ++detailSeq;
  sourceView.loading = true;
  sourceView.sourceId = sourceId;
  // Clear stale detail immediately so a row switch never shows the prior
  // source's domains/count while the new fetch is in flight.
  sourceView.domains = [];
  sourceView.resolvedCount = 0;
  sourceView.error = null;
  try {
    const detail = await apiGet(`/v1/sources/${sourceId}`, { auth: true });
    if (mine !== detailSeq) return; // a newer selection superseded this one
    sourceView.domains = (detail.domains ?? [])
      .filter((d) => d.removed_at == null)
      .map((d) => d.pattern);
    sourceView.resolvedCount = detail.resolved_artifact_count ?? 0;
    sourceView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    sourceView.error = e.message ?? String(e);
    sourceView.domains = [];
    sourceView.resolvedCount = 0;
  } finally {
    if (mine === detailSeq) sourceView.loading = false;
  }
}
