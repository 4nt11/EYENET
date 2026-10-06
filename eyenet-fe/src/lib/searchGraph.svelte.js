// Search-as-graph state. GET /v1/search/graph returns the induced subgraph for
// the SAME query + facets as the table view (so the two tabs are two lenses on
// one result set): nodes capped server-side (default 300, <=500). Edges carry a
// `provenance` — "derived" (machine-inferred, read-only) or "asserted" (an
// operator-mapped, durable, audited edge the UI can add/remove). The assert/
// retract calls persist per edit (POST/DELETE /v1/graph/edges) — this IS the
// autosave. Svelte 5 runes in a module, same shape as search.svelte.js.
import { apiGet, apiPost, apiDelete } from './api.js';
import { searchCtx } from './search.svelte.js';

export const graphCtx = $state({
  q: '',
  nodes: [],
  edges: [],
  sourceLabels: {},
  loaded: false,
  loading: false,
  error: null,
  // Mutation feedback for the edit modals (separate from a fetch error).
  mutating: false,
  mutateError: null
});

function mapNode(n) {
  return {
    entityType: n.entity_type,
    id: n.entity_id,
    title: n.title ?? '',
    status: n.status ?? null,
    sourceId: n.source_id ?? null,
    fields: n.fields ?? {}
  };
}

function mapEdge(e) {
  return {
    srcId: e.src_id,
    dstId: e.dst_id,
    kind: e.kind,
    weight: e.weight ?? null,
    provenance: e.provenance,
    edgeId: e.edge_id ?? null,
    reason: e.reason ?? null
  };
}

function graphQuery() {
  // Mirror the table's query + facets (one query, two lenses). The graph takes a
  // multi-valued `types` csv; the table facet is single-select so it's a 1-item csv.
  const p = new URLSearchParams({ q: graphCtx.q, limit: '300' });
  if (searchCtx.typeFilter) p.set('types', searchCtx.typeFilter);
  if (searchCtx.sourceFilter) p.set('source', searchCtx.sourceFilter);
  return p.toString();
}

// Monotonic token so a slow in-flight request can't clobber a newer one.
let seq = 0;

export async function runGraph(q) {
  const term = (q ?? '').trim();
  graphCtx.q = term;
  if (term === '') {
    graphCtx.nodes = [];
    graphCtx.edges = [];
    graphCtx.sourceLabels = {};
    graphCtx.error = null;
    graphCtx.loaded = false;
    graphCtx.loading = false;
    return;
  }
  const mine = ++seq;
  graphCtx.loading = true;
  graphCtx.loaded = false;
  try {
    const g = await apiGet(`/v1/search/graph?${graphQuery()}`, { auth: true });
    if (mine !== seq) return; // superseded by a newer query/facet change
    graphCtx.nodes = (g.nodes ?? []).map(mapNode);
    graphCtx.edges = (g.edges ?? []).map(mapEdge);
    graphCtx.sourceLabels = g.source_labels ?? {};
    graphCtx.error = null;
  } catch (e) {
    if (mine !== seq) return;
    graphCtx.error = e.message ?? String(e);
    graphCtx.nodes = [];
    graphCtx.edges = [];
    graphCtx.sourceLabels = {};
  } finally {
    if (mine === seq) {
      graphCtx.loading = false;
      graphCtx.loaded = true;
    }
  }
}

// Persist an operator-mapped edge, then reflect it on the canvas as asserted.
// `src`/`dst` are the two node rows (carrying entityType + id). Returns the new
// edge object on success; throws (with problem+json detail) on failure so the
// modal can surface it.
export async function assertEdge(src, dst, kind, reason) {
  graphCtx.mutating = true;
  graphCtx.mutateError = null;
  try {
    const res = await apiPost(
      '/v1/graph/edges',
      {
        src_type: src.entityType,
        src_id: src.id,
        dst_type: dst.entityType,
        dst_id: dst.id,
        kind,
        reason
      },
      { auth: true }
    );
    const edge = {
      srcId: res.src_id ?? src.id,
      dstId: res.dst_id ?? dst.id,
      kind: res.kind ?? kind,
      weight: null,
      provenance: 'asserted',
      edgeId: res.edge_id,
      reason
    };
    graphCtx.edges = [...graphCtx.edges, edge];
    return edge;
  } catch (e) {
    graphCtx.mutateError = e.message ?? String(e);
    throw e;
  } finally {
    graphCtx.mutating = false;
  }
}

// Retract an asserted edge (derived edges are read-only — the caller must not
// offer this for them). Removes it from the canvas on a successful 204.
export async function retractEdge(edgeId, reason) {
  graphCtx.mutating = true;
  graphCtx.mutateError = null;
  try {
    await apiDelete(`/v1/graph/edges/${edgeId}?reason=${encodeURIComponent(reason)}`, { auth: true });
    graphCtx.edges = graphCtx.edges.filter((e) => e.edgeId !== edgeId);
  } catch (e) {
    graphCtx.mutateError = e.message ?? String(e);
    throw e;
  } finally {
    graphCtx.mutating = false;
  }
}

// Human-readable name for a source id within the graph view.
const short = (id) => (id ? id.slice(0, 8) : '');
export function graphSourceName(id) {
  if (!id) return '';
  return graphCtx.sourceLabels[id] ?? short(id);
}
