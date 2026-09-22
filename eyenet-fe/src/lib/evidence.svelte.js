// Case-evidence workspace state. Case-scoped observation list from
// GET /v1/cases/{caseId}/observations (direct case members only). There is no
// observation-detail endpoint, so the detail panel renders the selected row's
// own fields. Keyed on the active case (caseCtx.active) — no active case means
// an honest empty state, not a fabricated list.
import { apiGet } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');

export const tierTone = (t) =>
  t === 'classified' ? 'critical' : t === 'restricted' ? 'high' : 'neutral';

function mapObservation(o) {
  return {
    id: o.observation_id,
    idShort: short(o.observation_id),
    kind: o.kind, // "namespace:name"
    primitive: o.primitive ?? '',
    observed: shortTs(o.ts),
    score: o.score,
    scoreText: o.score == null ? '·' : o.score.toFixed(2),
    sensitivity: o.sensitivity,
    attachmentBlobId: o.attachment_blob_id ?? null
  };
}

export const evidenceCtx = $state({ list: [], loaded: false, error: null, caseId: null });

let seq = 0;

export async function loadCaseObservations(caseId) {
  const mine = ++seq;
  evidenceCtx.loaded = false;
  evidenceCtx.caseId = caseId ?? null;
  evidenceCtx.list = [];
  evidenceCtx.error = null;
  if (!caseId) {
    evidenceCtx.loaded = true;
    return;
  }
  try {
    const page = await apiGet(`/v1/cases/${caseId}/observations?limit=200`, { auth: true });
    if (mine !== seq) return;
    evidenceCtx.list = page.items.map(mapObservation);
    evidenceCtx.error = null;
  } catch (e) {
    if (mine !== seq) return;
    evidenceCtx.error = e.message ?? String(e);
    evidenceCtx.list = [];
  } finally {
    if (mine === seq) evidenceCtx.loaded = true;
  }
}
