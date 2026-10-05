// Global cross-entity search state. GET /v1/search is FTS over every indexed
// entity type; `q` is REQUIRED (1..256) — an empty box stays idle and fetches
// nothing. Facets narrow server-side: `types` (one entity_type) and `source`
// (a source UUID). Paging is the backend's opaque cursor; include_total only on
// the first page so the header can show the match count. Svelte 5 runes in a
// module, same shape as graph.svelte.js / linkage.svelte.js.
import { apiGet } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '');

// SearchHit → the row shape the DataTable consumes. entity_id is the rowKey; we
// keep the raw type so the page can group + route per entity_type.
function mapHit(h) {
  return {
    entityType: h.entity_type,
    id: h.entity_id,
    title: h.title ?? '',
    subtitle: h.subtitle ?? '',
    status: h.status ?? '',
    sourceId: h.source_id ?? null,
    sourceShort: h.source_id ? short(h.source_id) : ''
  };
}

export const searchCtx = $state({
  q: '',
  items: [],
  byType: {},
  bySource: {},
  nextCursor: null,
  total: null,
  loaded: false,
  error: null,
  loadingMore: false,
  typeFilter: null,
  sourceFilter: null
});

function searchQuery(cursor) {
  const p = new URLSearchParams({ q: searchCtx.q, limit: '50' });
  if (searchCtx.typeFilter) p.set('types', searchCtx.typeFilter);
  if (searchCtx.sourceFilter) p.set('source', searchCtx.sourceFilter);
  if (cursor) p.set('cursor', cursor);
  else p.set('include_total', '1');
  return p.toString();
}

// Monotonic token so a slow in-flight request can't clobber a newer one.
let seq = 0;

export async function runSearch(q) {
  const term = (q ?? '').trim();
  searchCtx.q = term;
  if (term === '') {
    // Empty box → idle. Fetch nothing; clear any prior result + facets.
    searchCtx.items = [];
    searchCtx.byType = {};
    searchCtx.bySource = {};
    searchCtx.nextCursor = null;
    searchCtx.total = null;
    searchCtx.error = null;
    searchCtx.loaded = false;
    return;
  }
  const mine = ++seq;
  searchCtx.loaded = false;
  try {
    const page = await apiGet(`/v1/search?${searchQuery()}`, { auth: true });
    if (mine !== seq) return; // a newer search superseded this one
    searchCtx.items = page.items.map(mapHit);
    searchCtx.byType = page.by_type ?? {};
    searchCtx.bySource = page.by_source ?? {};
    searchCtx.nextCursor = page.next_cursor ?? null;
    searchCtx.total = page.estimated_total ?? null;
    searchCtx.error = null;
  } catch (e) {
    if (mine !== seq) return;
    searchCtx.error = e.message ?? String(e);
    searchCtx.items = [];
    searchCtx.byType = {};
    searchCtx.bySource = {};
    searchCtx.nextCursor = null;
  } finally {
    if (mine === seq) searchCtx.loaded = true;
  }
}

export async function loadMoreSearch() {
  if (!searchCtx.nextCursor || searchCtx.loadingMore) return;
  searchCtx.loadingMore = true;
  try {
    const page = await apiGet(`/v1/search?${searchQuery(searchCtx.nextCursor)}`, { auth: true });
    searchCtx.items = [...searchCtx.items, ...page.items.map(mapHit)];
    searchCtx.nextCursor = page.next_cursor ?? null;
  } catch (e) {
    searchCtx.error = e.message ?? String(e);
  } finally {
    searchCtx.loadingMore = false;
  }
}

// Facet toggles — clicking an active chip clears it (back to "all"). Each
// re-runs the search server-side with the new filter.
export function setTypeFilter(t) {
  searchCtx.typeFilter = searchCtx.typeFilter === t ? null : t;
  runSearch(searchCtx.q);
}

export function setSourceFilter(s) {
  searchCtx.sourceFilter = searchCtx.sourceFilter === s ? null : s;
  runSearch(searchCtx.q);
}
