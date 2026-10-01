// Incidents triage state. List from GET /v1/incidents (a CursorPage envelope:
// { items, next_cursor, estimated_total }, newest first; optional ?label= filters
// to one taxonomy head, ?include_total=1 asks for the count). Read-only: each row
// carries everything the dossier shows (labels, per-head scores, model version,
// timestamp), so selecting one needs no second fetch. Svelte 5 runes in a module,
// same shape as linkage.svelte.js.
import { apiGet, apiPut } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '');

function mapIncident(r) {
  const scores = r.scores ?? {};
  return {
    id: r.message_id,
    idShort: short(r.message_id),
    body: r.body ?? null,
    group: r.group ?? null, // WHERE: channel/group title
    groupId: r.group_id ?? null, // group id (drives the group filter)
    actorId: r.actor_id ?? null, // WHO: sender actor (dossier link)
    actorHandle: r.actor_handle ?? null,
    victimCountry: r.victim_country ?? null, // WHERE (victim): ISO alpha-2, null if unknown
    labels: r.labels ?? [],
    // per-head scores as [label, prob] rows, highest first (for the detail pane)
    scoreRows: Object.entries(scores).sort((a, b) => b[1] - a[1]),
    scores,
    modelVersion: r.model_version ?? '',
    classifiedAt: shortTs(r.classified_at),
    correctedLabels: r.corrected_labels ?? null, // operator ground truth (null = not corrected)
    correctedBy: r.corrected_by ?? null,
    correctedAt: shortTs(r.corrected_at)
  };
}

export const incidentCtx = $state({
  list: [],
  total: null, // estimated_total from the page envelope (null until loaded / if unavailable)
  nextCursor: null, // opaque cursor for the next page, null when this is the last
  loadingMore: false, // guards the "Load more" append against double-fire
  loaded: false,
  error: null,
  labels: [],
  q: '',
  groupIds: [],
  groups: [], // {id, title, count} for the group filter (full set, not window-limited)
  sourceIds: [],
  sources: [], // {id, title, count} for the source-level filter (e.g. a whole forum)
  countryCodes: [], // selected ISO alpha-2 victim-country filter (show-only)
  countries: [] // {code, count} options for the victim-country filter
});

// Build the /v1/incidents query from the current filter set (+ optional cursor for the
// next page). One builder so loadIncidents and loadMoreIncidents can never diverge on
// which filters they apply — the pager must page the SAME filtered set.
function incidentsQuery(cursor) {
  const params = new URLSearchParams({ limit: '200', include_total: '1' });
  for (const l of incidentCtx.labels) params.append('label', l); // repeated ?label= (OR)
  for (const g of incidentCtx.groupIds) params.append('group_id', g); // show-only groups
  for (const s of incidentCtx.sourceIds) params.append('source_id', s); // show-only sources
  for (const c of incidentCtx.countryCodes) params.append('victim_country', c); // show-only countries
  if (incidentCtx.q) params.set('q', incidentCtx.q); // free-text over message body (FTS5)
  if (cursor) params.set('cursor', cursor); // opaque next-page cursor
  return `/v1/incidents?${params}`;
}

// The complete set of groups that have incidents (noisiest first) — populates the group
// filter independently of the 200-row feed window. Load once; it grows slowly.
export async function loadIncidentGroups() {
  try {
    const rows = await apiGet('/v1/incidents/groups', { auth: true });
    if (Array.isArray(rows)) {
      incidentCtx.groups = rows.map((g) => ({
        id: g.group_id,
        title: g.title ?? g.group_id.slice(0, 8),
        sourceId: g.source_id,
        count: g.count
      }));
    }
  } catch {
    // Non-critical: a blocked/failed fetch (e.g. not logged in) just leaves the group
    // filter empty; the feed and other filters are unaffected (quiet-degrade like loadIncidents).
  }
}

// The complete set of SOURCES that have incidents (noisiest first) — the source-level
// filter, so a whole forum ("Darkforums") is one option instead of thousands of threads.
export async function loadIncidentSources() {
  try {
    const rows = await apiGet('/v1/incidents/sources', { auth: true });
    if (Array.isArray(rows)) {
      incidentCtx.sources = rows.map((s) => ({
        id: s.source_id,
        title: s.title ?? s.source_id.slice(0, 8),
        count: s.count
      }));
    }
  } catch {
    // Non-critical: leaves the source filter empty; feed and other filters unaffected.
  }
}

// The complete set of resolved victim COUNTRIES that have incidents (noisiest first) —
// the victim-country filter's options. ?q= is a body search and never matched the geo
// verdict, so this is how you actually find "Chile incidents".
export async function loadIncidentCountries() {
  try {
    const rows = await apiGet('/v1/incidents/countries', { auth: true });
    if (Array.isArray(rows)) {
      incidentCtx.countries = rows.map((c) => ({ code: c.country, count: c.count }));
    }
  } catch {
    // Non-critical: leaves the country filter empty; feed and other filters unaffected.
  }
}

// labels: taxonomy leaves (OR, repeated ?label=). groupIds/sourceIds/countryCodes: show
// ONLY those groups/sources/victim-countries (repeated params); empty = all. Replaces the
// list with the first page and resets the cursor.
export async function loadIncidents(
  labels = [],
  q = '',
  groupIds = [],
  sourceIds = [],
  countryCodes = []
) {
  incidentCtx.labels = labels;
  incidentCtx.q = q;
  incidentCtx.groupIds = groupIds;
  incidentCtx.sourceIds = sourceIds;
  incidentCtx.countryCodes = countryCodes;
  try {
    // GET /v1/incidents is a CursorPage envelope: { items, next_cursor, estimated_total }.
    const page = await apiGet(incidentsQuery(), { auth: true });
    incidentCtx.list = (page.items ?? []).map(mapIncident);
    incidentCtx.total = page.estimated_total ?? null;
    incidentCtx.nextCursor = page.next_cursor ?? null;
    incidentCtx.error = null;
  } catch (e) {
    incidentCtx.error = e.message ?? String(e);
    incidentCtx.list = [];
    incidentCtx.total = null;
    incidentCtx.nextCursor = null;
  } finally {
    incidentCtx.loaded = true;
  }
}

// Append the next cursor page (the "Load more" action). Same filter set as loadIncidents
// via incidentsQuery, so paging never silently changes what's filtered.
export async function loadMoreIncidents() {
  if (!incidentCtx.nextCursor || incidentCtx.loadingMore) return;
  incidentCtx.loadingMore = true;
  try {
    const page = await apiGet(incidentsQuery(incidentCtx.nextCursor), { auth: true });
    incidentCtx.list = [...incidentCtx.list, ...(page.items ?? []).map(mapIncident)];
    incidentCtx.nextCursor = page.next_cursor ?? null;
  } catch (e) {
    incidentCtx.error = e.message ?? String(e);
  } finally {
    incidentCtx.loadingMore = false;
  }
}

// Relabel state for the detail pane's editor (per-selection submit feedback).
export const incidentEdit = $state({ submitting: false, msg: null });

// Operator ground-truth correction. labels may be [] (false positive). On success,
// patches the in-memory row so the UI reflects the correction without a full reload.
export async function relabelIncident(messageId, labels, reason) {
  incidentEdit.submitting = true;
  incidentEdit.msg = null;
  try {
    const saved = await apiPut(
      `/v1/incidents/${messageId}/labels`,
      { labels, reason: reason || null },
      { auth: true, headers: { 'Idempotency-Key': crypto.randomUUID() } }
    );
    const row = incidentCtx.list.find((x) => x.id === messageId);
    if (row) {
      row.correctedLabels = saved.labels;
      row.correctedBy = saved.decided_by;
      row.correctedAt = shortTs(saved.decided_at);
    }
    incidentEdit.msg = 'Saved.';
    return true;
  } catch (e) {
    incidentEdit.msg = `Failed: ${e.message ?? e}`;
    return false;
  } finally {
    incidentEdit.submitting = false;
  }
}
