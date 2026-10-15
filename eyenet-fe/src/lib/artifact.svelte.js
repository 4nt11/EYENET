// Artifacts browser state. List from GET /v1/artifacts (deduped artifacts with
// read-time mention aggregates: how many, by how many actors, in how many groups,
// first/last seen). Selecting one fetches GET /v1/artifacts/{id}/mentions — the
// who / where / when drill-down, one row per sighting.
import { apiGet } from './api.js';

const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');
const short = (id) => (id ? id.slice(0, 8) : '');

function mapArtifact(a) {
  return {
    id: a.id,
    kind: a.kind,
    value: a.value,
    resolutionState: a.resolution_state,
    resolvedToSourceId: a.resolved_to_source_id ?? null,
    firstSeen: shortTs(a.first_seen_at_ingest),
    lastSeen: shortTs(a.last_seen_at_ingest),
    mentions: a.mention_count ?? 0,
    actors: a.distinct_actors ?? 0,
    groups: a.distinct_groups ?? 0,
    firstMention: shortTs(a.first_mention_at),
    lastMention: shortTs(a.last_mention_at)
  };
}

function mapMention(m) {
  return {
    messageId: m.message_id,
    actorId: m.actor_id,
    who: m.actor_handle || m.actor_display_name || short(m.actor_id),
    groupId: m.group_id,
    where: m.group_title || short(m.group_id),
    sourceId: m.source_id,
    when: shortTs(m.ts),
    charOffset: m.char_offset
  };
}

export const artifactCtx = $state({
  list: [],
  loaded: false,
  error: null,
  nextCursor: null,
  loadingMore: false,
  total: null
});

// Filters. kind '' = all; q = case-insensitive value substring; resolutionState ''
// = all. sort: recent | mentions | value | first_seen.
export const artifactFilters = $state({
  sort: 'recent',
  kind: '',
  q: '',
  resolutionState: ''
});

export const artifactView = $state({
  detailId: null,
  mentions: [],
  mentionsCursor: null,
  mentionsTotal: null,
  loading: false,
  loadingMore: false,
  error: null
});

const _PAGE = 100;

function _query(extra = '') {
  const p = new URLSearchParams();
  p.set('limit', String(_PAGE));
  p.set('include_total', '1');
  p.set('sort', artifactFilters.sort);
  if (artifactFilters.kind) p.set('kind', artifactFilters.kind);
  if (artifactFilters.q.trim()) p.set('q', artifactFilters.q.trim());
  if (artifactFilters.resolutionState) p.set('resolution_state', artifactFilters.resolutionState);
  return `/v1/artifacts?${p.toString()}${extra}`;
}

export async function loadArtifacts() {
  try {
    const page = await apiGet(_query(), { auth: true });
    artifactCtx.list = page.items.map(mapArtifact);
    artifactCtx.nextCursor = page.next_cursor ?? null;
    artifactCtx.total = page.estimated_total ?? null;
    artifactCtx.error = null;
  } catch (e) {
    artifactCtx.error = e.message ?? String(e);
    artifactCtx.list = [];
    artifactCtx.nextCursor = null;
  } finally {
    artifactCtx.loaded = true;
  }
}

export async function loadMoreArtifacts() {
  if (!artifactCtx.nextCursor || artifactCtx.loadingMore) return;
  artifactCtx.loadingMore = true;
  try {
    const page = await apiGet(_query(`&cursor=${encodeURIComponent(artifactCtx.nextCursor)}`), { auth: true });
    artifactCtx.list = [...artifactCtx.list, ...page.items.map(mapArtifact)];
    artifactCtx.nextCursor = page.next_cursor ?? null;
  } catch (e) {
    artifactCtx.error = e.message ?? String(e);
  } finally {
    artifactCtx.loadingMore = false;
  }
}

// Debounced refetch on filter change (the search box fires per keystroke).
let _t = null;
export function applyFilters() {
  if (_t) clearTimeout(_t);
  _t = setTimeout(() => loadArtifacts(), 200);
}

export async function loadArtifactMentions(artifactId) {
  artifactView.detailId = artifactId;
  artifactView.loading = true;
  artifactView.error = null;
  try {
    const page = await apiGet(
      `/v1/artifacts/${artifactId}/mentions?limit=${_PAGE}&include_total=1`,
      { auth: true }
    );
    artifactView.mentions = page.items.map(mapMention);
    artifactView.mentionsCursor = page.next_cursor ?? null;
    artifactView.mentionsTotal = page.estimated_total ?? null;
  } catch (e) {
    artifactView.error = e.message ?? String(e);
    artifactView.mentions = [];
    artifactView.mentionsCursor = null;
  } finally {
    artifactView.loading = false;
  }
}

export async function loadMoreMentions(artifactId) {
  if (!artifactView.mentionsCursor || artifactView.loadingMore) return;
  artifactView.loadingMore = true;
  try {
    const page = await apiGet(
      `/v1/artifacts/${artifactId}/mentions?limit=${_PAGE}&cursor=${encodeURIComponent(artifactView.mentionsCursor)}`,
      { auth: true }
    );
    artifactView.mentions = [...artifactView.mentions, ...page.items.map(mapMention)];
    artifactView.mentionsCursor = page.next_cursor ?? null;
  } catch (e) {
    artifactView.error = e.message ?? String(e);
  } finally {
    artifactView.loadingMore = false;
  }
}
