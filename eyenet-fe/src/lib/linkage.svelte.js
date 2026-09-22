// Linkages workspace state. List from GET /v1/linkages; selecting one fetches
// GET /v1/linkages/{id} for its evidence and resolves both actors' handles
// (the list carries only UUIDs). Decisions POST to confirm/suspect/reject with
// an Idempotency-Key. Svelte 5 runes in a module, same shape as case.svelte.js.
import { apiGet, apiPost } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '');

// evidence.detail is a free-form object (additionalProperties) — render a
// compact "k=v · k=v" string. Function decl (hoisted) so the mapper below can
// call it regardless of order.
function fmtEvidenceDetail(d) {
  if (d == null) return '';
  if (typeof d !== 'object') return String(d);
  return Object.entries(d)
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(' · ');
}

function mapLinkage(l) {
  return {
    id: l.linkage_id,
    idShort: short(l.linkage_id),
    actorAId: l.actor_a_id,
    actorBId: l.actor_b_id,
    pair: `${short(l.actor_a_id)} ↔ ${short(l.actor_b_id)}`,
    state: l.state,
    method: l.method ?? '',
    score: l.score,
    scoreText: l.score.toFixed(2),
    proposedAt: shortTs(l.proposed_at),
    decidedAt: shortTs(l.decided_at),
    decidedBy: l.decided_by ? short(l.decided_by) : null
  };
}

export const linkageCtx = $state({ list: [], loaded: false, error: null });

export async function loadLinkages() {
  try {
    const page = await apiGet('/v1/linkages?limit=200', { auth: true });
    linkageCtx.list = page.items.map(mapLinkage);
    linkageCtx.error = null;
  } catch (e) {
    linkageCtx.error = e.message ?? String(e);
    linkageCtx.list = [];
  } finally {
    linkageCtx.loaded = true;
  }
}

export const linkageView = $state({
  id: null,
  handleA: null,
  handleB: null,
  evidence: [],
  loading: false,
  error: null,
  submitting: false,
  submitMsg: null
});

// No user/actor directory beyond per-id fetch; resolve a handle or fall back to
// the short UUID. A 404 (unknown actor) is expected — swallow to the null path.
async function actorHandle(actorId) {
  try {
    const a = await apiGet(`/v1/actors/${actorId}`, { auth: true });
    return a.primary_handle ?? null;
  } catch {
    return null;
  }
}

let detailSeq = 0;

export async function loadLinkageDetail(id, actorAId, actorBId) {
  const mine = ++detailSeq;
  linkageView.loading = true;
  linkageView.id = id;
  // Clear stale detail immediately so a fast row switch never shows the prior
  // linkage's evidence/handles while the new fetch is in flight.
  linkageView.handleA = null;
  linkageView.handleB = null;
  linkageView.evidence = [];
  linkageView.error = null;
  linkageView.submitMsg = null;
  try {
    const [detail, handleA, handleB] = await Promise.all([
      apiGet(`/v1/linkages/${id}`, { auth: true }),
      actorHandle(actorAId),
      actorHandle(actorBId)
    ]);
    if (mine !== detailSeq) return; // superseded by a newer selection
    linkageView.evidence = (detail.evidence ?? []).map((e) => ({
      comparator: e.comparator,
      score: e.score.toFixed(2),
      detail: fmtEvidenceDetail(e.detail)
    }));
    linkageView.handleA = handleA;
    linkageView.handleB = handleB;
    linkageView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    linkageView.error = e.message ?? String(e);
    linkageView.evidence = [];
  } finally {
    if (mine === detailSeq) linkageView.loading = false;
  }
}

// decision ∈ {confirm, suspect, reject}. The POST is 202-accepted: the graph
// applies the state transition asynchronously off the bus, so the row may not
// flip immediately — we refresh and let it settle.
export async function decideLinkage(id, decision, reason, note) {
  linkageView.submitting = true;
  linkageView.submitMsg = null;
  try {
    await apiPost(
      `/v1/linkages/${id}/${decision}`,
      { reason, note: note || null },
      { auth: true, headers: { 'Idempotency-Key': crypto.randomUUID() } }
    );
    linkageView.submitMsg = `${decision} submitted — the graph applies it asynchronously.`;
    await loadLinkages();
  } catch (e) {
    linkageView.submitMsg = `Failed: ${e.message ?? e}`;
  } finally {
    linkageView.submitting = false;
  }
}
