// Exploration-canvas state: a graph the operator GROWS one enrichment hop at a
// time (unlike the search page, which renders a whole query's induced subgraph).
// Seed a node from global search, then right-click -> enrichment -> expand pulls
// neighbours via GET /v1/graph/expand and merges them in. Svelte 5 runes module;
// node/edge shapes match what GraphCanvas.svelte consumes (see searchGraph.svelte.js).
import { apiGet, apiPost, apiPut, apiDelete } from './api.js';

export const explorer = $state({
  nodes: [], // GraphCanvas node shape: { id, title, entityType, status, sourceId, fields }
  edges: [], // GraphCanvas edge shape: { srcId, dstId, kind, provenance, weight, edgeId }
  busy: false,
  error: null,
  // seed-search sub-state (the top-of-canvas box)
  seedResults: [],
  seedLoading: false
});

// SearchGraphNode / SearchHit -> GraphCanvas node. Both carry entity_type /
// entity_id / title / fields, so one mapper serves seed hits and expand neighbours.
function mapNode(n) {
  return {
    id: n.entity_id,
    title: n.title ?? n.entity_id,
    entityType: n.entity_type,
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
    provenance: e.provenance ?? 'derived',
    weight: e.weight ?? null,
    edgeId: e.edge_id ?? null
  };
}

const edgeKey = (e) => e.edgeId ?? `${e.srcId}:${e.dstId}:${e.kind}`;

function addNode(n) {
  if (!explorer.nodes.some((x) => x.id === n.id)) explorer.nodes = [...explorer.nodes, n];
}
function addEdge(e) {
  if (!explorer.edges.some((x) => edgeKey(x) === edgeKey(e))) explorer.edges = [...explorer.edges, e];
}

// Drop a search hit onto the canvas as a seed node (idempotent by id).
export function addSeed(hit) {
  addNode(mapNode(hit));
}

let seedSeq = 0;
export async function seedSearch(q) {
  const term = q.trim();
  if (term === '') {
    explorer.seedResults = [];
    explorer.seedLoading = false;
    return;
  }
  const mine = ++seedSeq;
  explorer.seedLoading = true;
  try {
    const page = await apiGet(`/v1/search?q=${encodeURIComponent(term)}&limit=20`, { auth: true });
    if (mine !== seedSeq) return;
    explorer.seedResults = page.items ?? [];
  } catch (e) {
    if (mine !== seedSeq) return;
    explorer.seedResults = [];
    explorer.error = e.message ?? String(e);
  } finally {
    if (mine === seedSeq) explorer.seedLoading = false;
  }
}

// Degree preview for the right-click menu. { enrichment_name: count | null }
// (null = remote enrichment, count unknown until expanded).
export async function fetchCounts(node) {
  const r = await apiGet(
    `/v1/graph/expand/counts?type=${node.entityType}&id=${node.id}`,
    { auth: true }
  );
  return r.counts ?? {};
}

// One enrichment hop: fetch neighbours + edges and merge them into the canvas.
export async function expandNode(node, enrichment) {
  explorer.busy = true;
  explorer.error = null;
  try {
    const r = await apiGet(
      `/v1/graph/expand?type=${node.entityType}&id=${node.id}` +
        `&enrichment=${encodeURIComponent(enrichment)}&limit=50`,
      { auth: true }
    );
    for (const n of r.nodes ?? []) addNode(mapNode(n));
    for (const e of r.edges ?? []) addEdge(mapEdge(e));
  } catch (e) {
    explorer.error = e.message ?? String(e);
  } finally {
    explorer.busy = false;
  }
}

// Predefined operator edge kinds (asserted_edge.kind is open varchar, so custom
// free-text is allowed too). Locked set from GRAPH_EXPLORER.md §8.
export const EDGE_KINDS = [
  'same_as',
  'associate_of',
  'controls',
  'member_of',
  'uses',
  'communicates_with',
  'related_to'
];

// Shift-drag between two nodes -> persist an operator-asserted edge, reflect it
// on the canvas (solid/asserted). `src`/`dst` are the mapped node rows.
export async function assertEdge(src, dst, kind, reason) {
  explorer.busy = true;
  explorer.error = null;
  try {
    const res = await apiPost(
      '/v1/graph/edges',
      { src_type: src.entityType, src_id: src.id, dst_type: dst.entityType, dst_id: dst.id, kind, reason },
      { auth: true }
    );
    addEdge({
      srcId: res.src_id ?? src.id,
      dstId: res.dst_id ?? dst.id,
      kind: res.kind ?? kind,
      provenance: 'asserted',
      weight: null,
      edgeId: res.edge_id ?? null
    });
  } catch (e) {
    explorer.error = e.message ?? String(e);
    throw e;
  } finally {
    explorer.busy = false;
  }
}

// Per-entity note (the inspector Notes field). loadNote returns the body string
// ('' when none); saveNote upserts; deleteNote removes.
export async function loadNote(node) {
  try {
    const r = await apiGet(`/v1/notes/${node.entityType}/${node.id}`, { auth: true });
    return r.body ?? '';
  } catch (e) {
    if (e.status === 404) return '';
    throw e;
  }
}
export async function saveNote(node, body) {
  await apiPut(`/v1/notes/${node.entityType}/${node.id}`, { body }, { auth: true });
}
export async function deleteNote(node) {
  await apiDelete(`/v1/notes/${node.entityType}/${node.id}`, { auth: true });
}

export function clearGraph() {
  explorer.nodes = [];
  explorer.edges = [];
  explorer.seedResults = [];
  explorer.error = null;
}
