// Candidate-triage workspace state. List from GET /v1/candidates; selecting one
// fetches GET /v1/candidates/{id} (mentions, score breakdown, review state) and
// resolves the source label (the row carries only a source_id UUID). Decisions
// POST to approve/reject/park — 202 but the transition is applied in-handler, so
// the returned detail already reflects the new state (no poll, unlike linkages/
// collectors which settle off the bus). Svelte 5 runes, same shape as
// linkage.svelte.js.
import { apiGet, apiPost } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '—');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');

// Real CandidateState (lowercase on the wire): discovered → queued → approved →
// joining → joined, plus requested (approval-gated join), rejected, failed,
// parked. There is NO `pending` — the mock invented it. Only `queued` and
// `joined` carry an operator action; everything else is informational.
const TONE = {
  queued: 'warn',
  discovered: 'neutral',
  approved: 'high',
  joining: 'warn',
  joined: 'high',
  requested: 'accent',
  rejected: 'critical',
  failed: 'critical',
  parked: 'low'
};
export const candidateTone = (s) => TONE[s] ?? 'neutral';

function fmtBreakdown(b) {
  if (b == null || typeof b !== 'object') return [];
  return Object.entries(b).map(([k, v]) => ({
    k,
    v: typeof v === 'object' ? JSON.stringify(v) : String(v)
  }));
}

function mapCandidate(c) {
  return {
    id: c.candidate_id,
    idShort: short(c.candidate_id),
    sourceId: c.source_id,
    group: c.display_name_hint || c.platform_groupid,
    platformGroupId: c.platform_groupid,
    kindHint: c.kind_hint ?? '',
    state: c.state,
    score: c.score,
    scoreText: c.score.toFixed(2),
    firstObserved: shortTs(c.first_observed_at_ingest),
    lastObserved: shortTs(c.last_observed_at_ingest)
  };
}

export const candidateCtx = $state({ list: [], loaded: false, error: null });

export async function loadCandidates() {
  try {
    const page = await apiGet('/v1/candidates?limit=200', { auth: true });
    candidateCtx.list = page.items.map(mapCandidate);
    candidateCtx.error = null;
  } catch (e) {
    candidateCtx.error = e.message ?? String(e);
    candidateCtx.list = [];
  } finally {
    candidateCtx.loaded = true;
  }
}

export const candidateView = $state({
  id: null,
  source: null,
  breakdown: [],
  mentions: [],
  reviewedBy: null,
  reviewedAt: null,
  rejectionReason: null,
  assignedCollector: null,
  resultingGroup: null,
  loading: false,
  error: null,
  submitting: false,
  submitMsg: null
});

// No source-directory beyond per-id fetch; resolve a human label or fall back to
// the short UUID. A 404 is expected for a stale source — swallow to the null path.
async function sourceLabel(sourceId) {
  try {
    const s = await apiGet(`/v1/sources/${sourceId}`, { auth: true });
    return s.kind ?? s.platform ?? s.display_name ?? null;
  } catch {
    return null;
  }
}

let detailSeq = 0;

export async function loadCandidateDetail(id, sourceId) {
  const mine = ++detailSeq;
  candidateView.loading = true;
  candidateView.id = id;
  // Clear stale detail immediately so a fast row switch never shows the prior
  // candidate's mentions/breakdown while the new fetch is in flight.
  candidateView.source = null;
  candidateView.breakdown = [];
  candidateView.mentions = [];
  candidateView.reviewedBy = null;
  candidateView.reviewedAt = null;
  candidateView.rejectionReason = null;
  candidateView.assignedCollector = null;
  candidateView.resultingGroup = null;
  candidateView.error = null;
  candidateView.submitMsg = null;
  try {
    const [detail, source] = await Promise.all([
      apiGet(`/v1/candidates/${id}`, { auth: true }),
      sourceLabel(sourceId)
    ]);
    if (mine !== detailSeq) return; // superseded by a newer selection
    candidateView.source = source;
    candidateView.breakdown = fmtBreakdown(detail.score_breakdown);
    candidateView.mentions = (detail.mentions ?? []).map((m) => ({
      id: m.mention_id,
      kind: m.mention_kind,
      actor: short(m.mentioning_actor_id),
      role: m.mentioning_actor_role_signal ?? '',
      depth: m.depth_from_root,
      evidence: m.mention_evidence_ref
    }));
    candidateView.reviewedBy = detail.reviewed_by ?? null;
    candidateView.reviewedAt = shortTs(detail.reviewed_at) === '·' ? null : shortTs(detail.reviewed_at);
    candidateView.rejectionReason = detail.rejection_reason ?? null;
    candidateView.assignedCollector = detail.assigned_collector_id ? short(detail.assigned_collector_id) : null;
    candidateView.resultingGroup = detail.resulting_group_id ? short(detail.resulting_group_id) : null;
    candidateView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    candidateView.error = e.message ?? String(e);
  } finally {
    if (mine === detailSeq) candidateView.loading = false;
  }
}

// Post an approve/reject/park/retry. All are 202 with the transition applied
// synchronously in-handler, so the response body already carries the new state —
// no poll loop needed. `body` differs per action: approve → {assigned_collector_id},
// reject/park → {reason}, retry → {} (no body).
async function decide(id, sourceId, action, body, label) {
  candidateView.submitting = true;
  candidateView.submitMsg = null;
  try {
    await apiPost(`/v1/candidates/${id}/${action}`, body, { auth: true, accept: [202] });
    candidateView.submitMsg = `${label} applied.`;
    await loadCandidates();
    await loadCandidateDetail(id, sourceId);
  } catch (e) {
    candidateView.submitMsg = `Failed: ${e.message ?? e}`;
  } finally {
    candidateView.submitting = false;
  }
}

export const approveCandidate = (id, sourceId, collectorId) =>
  decide(id, sourceId, 'approve', { assigned_collector_id: collectorId }, 'Approve');
export const rejectCandidate = (id, sourceId, reason) =>
  decide(id, sourceId, 'reject', { reason }, 'Reject');
export const parkCandidate = (id, sourceId, reason) =>
  decide(id, sourceId, 'park', { reason }, 'Park');
// retry: failed → queued. Gated on admin:candidates (grant-only) server-side —
// retrying a rejected join can burn identities — so a caller without the grant
// gets a surfaced 403 in submitMsg.
export const retryCandidate = (id, sourceId) => decide(id, sourceId, 'retry', {}, 'Retry');
