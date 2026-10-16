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
  // seed-search sub-state (the palette box)
  seedResults: [],
  seedLoading: false,
  // palette scope: null = all; { types } = an entity_type facet; { dsl, id } = a query-DSL
  // predicate (e.g. artifact.kind:onion) so an artifact search doesn't return actors.
  seedScope: null,
  seedQ: '',
  // saved-graph identity (null = unsaved scratch canvas)
  graphId: null,
  graphName: ''
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
  explorer.seedQ = q;
  const sc = explorer.seedScope;
  // Build the search query. A DSL scope (artifact.kind:onion) is a valid query on its
  // own, so it can browse a kind with no term; an entity-type scope uses the facet and
  // needs a term (the API's q is min-length 1).
  let qParam = '';
  let typesParam = '';
  if (sc?.dsl) {
    qParam = term ? `${sc.dsl} ${term}` : sc.dsl;
  } else if (term) {
    qParam = term;
    if (sc?.types) typesParam = `&types=${encodeURIComponent(sc.types)}`;
  }
  if (!qParam) {
    explorer.seedResults = [];
    explorer.seedLoading = false;
    return;
  }
  const mine = ++seedSeq;
  explorer.seedLoading = true;
  try {
    const page = await apiGet(
      `/v1/search?q=${encodeURIComponent(qParam)}&limit=25${typesParam}`,
      { auth: true }
    );
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

// Palette click: scope the seed search (toggle off if the same scope). `scope` is
// { id, types } for an entity type or { id, dsl } for a query-DSL predicate.
export function setSeedScope(scope) {
  explorer.seedScope = explorer.seedScope?.id === scope.id ? null : scope;
  seedSearch(explorer.seedQ);
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

// One enrichment hop: pull ALL neighbours (follow the cursor to the end) and merge
// them into the canvas. The operator wants the whole set, not a first page; the
// canvas survives big sets because GraphCanvas disables its per-frame sim past a
// node threshold. A high safety ceiling guards against a pathological fan-out.
const EXPAND_MAX_NODES = 5000;
export async function expandNode(node, enrichment) {
  explorer.busy = true;
  explorer.error = null;
  try {
    let cursor = null;
    let added = 0;
    do {
      const qs =
        `type=${node.entityType}&id=${node.id}` +
        `&enrichment=${encodeURIComponent(enrichment)}&limit=200` +
        (cursor ? `&cursor=${encodeURIComponent(cursor)}` : '');
      const r = await apiGet(`/v1/graph/expand?${qs}`, { auth: true });
      for (const n of r.nodes ?? []) addNode(mapNode(n));
      for (const e of r.edges ?? []) addEdge(mapEdge(e));
      added += (r.nodes ?? []).length;
      cursor = r.next_cursor ?? null;
    } while (cursor && added < EXPAND_MAX_NODES);
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

// GroupKind values an operator may pick when hand-creating a group.
export const GROUP_KINDS = [
  'chat', 'channel', 'dm', 'forum_category', 'forum_thread', 'irc_channel', 'matrix_room'
];

// Hand-create an operator-asserted entity and drop it on the canvas. `type` is
// one of actor/group/artifact; `payload` matches the POST body. The create returns
// { id, entity_type }, so we synthesize the node (title from the operator input).
export async function createOperatorEntity(type, payload) {
  const path = type === 'actor' ? '/v1/actors' : type === 'group' ? '/v1/groups' : '/v1/artifacts';
  explorer.busy = true;
  explorer.error = null;
  try {
    const res = await apiPost(path, payload, { auth: true });
    const title =
      type === 'actor' ? (payload.handle || payload.display_name)
      : type === 'group' ? payload.title
      : payload.value;
    const fields =
      type === 'artifact'
        ? { kind: payload.kind, provenance: 'operator_asserted' }
        : { provenance: 'operator_asserted' };
    addNode({ id: res.id, title: title || res.id, entityType: res.entity_type, status: null, sourceId: null, fields });
    return res;
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

// ── Saved graphs (the picker). A saved graph persists the node SET + placements
// (x/y). NOTE for a later pass: titles are not stored (loaded nodes label by id
// until a batch-hydrate endpoint exists) and edges are not persisted per-graph
// (operator re-enriches; asserted edges live in the global store).
export async function listGraphs() {
  const page = await apiGet('/v1/graphs?limit=100', { auth: true });
  return page.items ?? [];
}

// Create a new empty saved graph (the picker's "New graph"); returns its id.
export async function createGraph(name) {
  const g = await apiPost('/v1/graphs', { name }, { auth: true });
  return g.id;
}

export async function saveGraph(name, positions) {
  explorer.busy = true;
  explorer.error = null;
  try {
    let gid = explorer.graphId;
    if (!gid) {
      const g = await apiPost('/v1/graphs', { name }, { auth: true });
      gid = g.id;
      explorer.graphId = gid;
      explorer.graphName = g.name ?? name;
    }
    const posById = Object.fromEntries((positions ?? []).map((p) => [p.id, p]));
    const nodes = explorer.nodes.map((n) => ({
      entity_type: n.entityType,
      entity_id: n.id,
      x: posById[n.id]?.x ?? 0,
      y: posById[n.id]?.y ?? 0,
      pinned: false,
      enrichments_run: []
    }));
    const edges = explorer.edges.map((e) => ({
      src_id: e.srcId,
      dst_id: e.dstId,
      kind: e.kind,
      provenance: e.provenance ?? 'derived',
      edge_id: e.edgeId ?? null
    }));
    await apiPut(`/v1/graphs/${gid}/nodes`, { nodes, edges }, { auth: true });
    return gid;
  } catch (e) {
    explorer.error = e.message ?? String(e);
    throw e;
  } finally {
    explorer.busy = false;
  }
}

export async function loadGraph(id) {
  explorer.busy = true;
  explorer.error = null;
  try {
    const g = await apiGet(`/v1/graphs/${id}`, { auth: true });
    explorer.graphId = g.id;
    explorer.graphName = g.name;
    let nodes = (g.nodes ?? []).map((n) => ({
      id: n.entity_id,
      entityType: n.entity_type,
      title: n.entity_id, // placeholder until hydrated below
      x: n.x,
      y: n.y,
      status: null,
      sourceId: null,
      fields: {}
    }));
    // Restore labels/fields from search_document (titles aren't persisted per-graph).
    const ids = nodes.map((n) => n.id);
    if (ids.length) {
      try {
        const h = await apiPost('/v1/graph/hydrate', { ids }, { auth: true });
        const byId = Object.fromEntries((h.nodes ?? []).map((x) => [x.entity_id, x]));
        nodes = nodes.map((n) => {
          const hit = byId[n.id];
          return hit
            ? { ...n, title: hit.title ?? n.title, status: hit.status ?? null, sourceId: hit.source_id ?? null, fields: hit.fields ?? {} }
            : n;
        });
      } catch { /* leave id-labelled on hydrate failure */ }
    }
    explorer.nodes = nodes;
    explorer.edges = (g.edges ?? []).map((e) => ({
      srcId: e.src_id,
      dstId: e.dst_id,
      kind: e.kind,
      provenance: e.provenance ?? 'derived',
      weight: null,
      edgeId: e.edge_id ?? null
    }));
    explorer.seedResults = [];
  } catch (e) {
    explorer.error = e.message ?? String(e);
    throw e;
  } finally {
    explorer.busy = false;
  }
}

export async function deleteGraph(id) {
  await apiDelete(`/v1/graphs/${id}`, { auth: true });
  if (explorer.graphId === id) {
    explorer.graphId = null;
    explorer.graphName = '';
  }
}

export function clearGraph() {
  explorer.nodes = [];
  explorer.edges = [];
  explorer.seedResults = [];
  explorer.error = null;
  explorer.graphId = null;
  explorer.graphName = '';
}
