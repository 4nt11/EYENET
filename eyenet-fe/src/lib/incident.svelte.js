// Incidents triage state. List from GET /v1/incidents (a plain array, newest
// first; optional ?label= filters to one taxonomy head). Read-only: each row
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
  loaded: false,
  error: null,
  labels: [],
  q: '',
  groupIds: [],
  groups: [], // {id, title, count} for the group filter (full set, not window-limited)
  sourceIds: [],
  sources: [] // {id, title, count} for the source-level filter (e.g. a whole forum)
});

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

// labels: taxonomy leaves (OR filter, repeated ?label=). groupIds: show ONLY these groups
// (repeated ?group_id=); sourceIds: show ONLY these sources (?source_id=); empty = all.
export async function loadIncidents(labels = [], q = '', groupIds = [], sourceIds = []) {
  incidentCtx.labels = labels;
  incidentCtx.q = q;
  incidentCtx.groupIds = groupIds;
  incidentCtx.sourceIds = sourceIds;
  const params = new URLSearchParams({ limit: '200' });
  for (const l of labels) params.append('label', l); // repeated ?label=a&label=b (OR)
  for (const g of groupIds) params.append('group_id', g); // show-only ?group_id=a&group_id=b
  for (const s of sourceIds) params.append('source_id', s); // show-only ?source_id=a&source_id=b
  if (q) params.set('q', q); // free-text over message body (FTS5 on the backend)
  try {
    const rows = await apiGet(`/v1/incidents?${params}`, { auth: true });
    incidentCtx.list = rows.map(mapIncident);
    incidentCtx.error = null;
  } catch (e) {
    incidentCtx.error = e.message ?? String(e);
    incidentCtx.list = [];
  } finally {
    incidentCtx.loaded = true;
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
