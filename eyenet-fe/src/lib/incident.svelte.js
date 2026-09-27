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

export const incidentCtx = $state({ list: [], loaded: false, error: null, label: null });

export async function loadIncidents(label = null) {
  incidentCtx.label = label;
  const q = label ? `?limit=200&label=${encodeURIComponent(label)}` : '?limit=200';
  try {
    const rows = await apiGet(`/v1/incidents${q}`, { auth: true });
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
