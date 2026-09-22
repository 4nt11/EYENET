// Active-case context. Cases behave like tenants: entering a case scopes the
// whole Cases workspace to it. Universal reactive state (Svelte 5 runes in a
// module). The caseload is fetched from GET /v1/cases (read:cases).
import { apiGet } from './api.js';
import { auth } from './auth.svelte.js';

// CaseSummary → the flat shape the cards/switcher/header consume. Keeping the
// `caseId`/`tier` names the mock used means the components barely change; `tier`
// here is the sensitivity tier (normal|restricted|classified), which TierBadge
// already renders.
function mapCase(c) {
  return {
    caseId: c.case_id,
    title: c.title,
    tier: c.effective_tier,
    status: c.status,
    created: c.created_at,
    memberCount: c.member_count ?? 0
  };
}

export const caseCtx = $state({ list: [], active: null, loaded: false, error: null });

export async function loadCases() {
  try {
    const page = await apiGet('/v1/cases', { auth: true });
    caseCtx.list = page.items.map(mapCase);
    caseCtx.error = null;
  } catch (e) {
    caseCtx.error = e.message ?? String(e);
    caseCtx.list = [];
  } finally {
    caseCtx.loaded = true;
  }
}

export function enterCase(caseId) {
  caseCtx.active = caseCtx.list.find((c) => c.caseId === caseId) ?? null;
}
export function exitCase() {
  caseCtx.active = null;
}

// ── Inside-a-case content ──────────────────────────────────────────────────
// Audit trail: /v1/audit?subject_id={caseId} — the per-case hash-chained trail
// (subject_id is the audited row's identity). Members: /v1/cases/{id}/members.
export const caseView = $state({ audit: [], members: [], loading: false, error: null });

// Best-effort human label for an audit row's target, from whatever the payload
// carries for that event kind.
function auditTarget(p) {
  return p.title ?? p.username ?? p.role ?? shortId(p.collaborator_id ?? p.linkage_id) ?? '';
}

const shortId = (id) => (id ? id.slice(0, 8) : '');
const shortTs = (ts) => ts.replace('T', ' ').replace(/\..*$/, 'Z');
const stripSubject = (s) => s.replace(/^eyenet\.(audit\.)?/, '');
// Chain/journal heads are long hex digests — clip for the anchors table.
const shortHash = (h) => (h && h.length > 20 ? `${h.slice(0, 10)}…${h.slice(-6)}` : (h ?? ''));

function resolveUser(uid) {
  if (!uid) return 'system';
  if (auth.user && uid === auth.user.user_id) return auth.user.username;
  return shortId(uid);
}

export async function loadCaseView(caseId) {
  caseView.loading = true;
  try {
    const [audit, members] = await Promise.all([
      apiGet(`/v1/audit?subject_id=${caseId}&limit=50`, { auth: true }),
      apiGet(`/v1/cases/${caseId}/members`, { auth: true })
    ]);
    caseView.audit = audit.items.map((r) => ({
      time: shortTs(r.ts),
      actor: resolveUser(r.user_id),
      verb: stripSubject(r.subject),
      target: auditTarget(r.payload ?? {}),
      tamper: false
    }));
    caseView.members = members.items.map((m) => ({
      id: shortId(m.subject_id),
      subjectId: m.subject_id,
      ts: shortTs(m.added_at),
      type: m.subject_kind,
      reason: m.add_reason,
      addedBy: resolveUser(m.added_by_user_id),
      active: m.active
    }));
    caseView.error = null;
  } catch (e) {
    caseView.error = e.message ?? String(e);
    caseView.audit = [];
    caseView.members = [];
  } finally {
    caseView.loading = false;
  }
}

// ── /cases/logs — full case trail + chain verify + external anchors ─────────
// The Logs page is the operator's tamper-evidence surface for one case:
//   - /v1/audit?subject_id={caseId}  — the case's hash-chained trail (§5.5)
//   - /v1/audit/verify               — recompute the chain, report any break
//   - /v1/audit/anchors              — external-witness records (§5.9)
// `tamper` is NOT a per-row flag: it's derived from the verify result's
// first_break, so a single divergent event lights up its own row.
export const logsView = $state({
  audit: [],
  verify: null, // { verified, entries, brokenEventId }
  anchors: [],
  loading: false,
  error: null
});

// Monotonic token so switching the active case can't let a slow response land
// after a newer one and show another case's trail.
let logsSeq = 0;

export async function loadCaseLogs(caseId) {
  const mine = ++logsSeq;
  logsView.loading = true;
  // Clear stale trail immediately so a case switch never shows the prior
  // case's events/anchors while the new fetch is in flight.
  logsView.audit = [];
  logsView.anchors = [];
  logsView.verify = null;
  logsView.error = null;
  try {
    const [audit, verify, anchors] = await Promise.all([
      apiGet(`/v1/audit?subject_id=${caseId}&limit=200`, { auth: true }),
      apiGet('/v1/audit/verify', { auth: true }),
      apiGet('/v1/audit/anchors?limit=50', { auth: true })
    ]);
    if (mine !== logsSeq) return; // a newer case selection superseded this one
    const brokenId = verify.first_break?.event_id ?? null;
    logsView.audit = audit.items.map((r) => ({
      time: shortTs(r.ts),
      actor: resolveUser(r.user_id),
      verb: stripSubject(r.subject),
      target: auditTarget(r.payload ?? {}),
      tamper: brokenId != null && r.event_id === brokenId
    }));
    logsView.verify = {
      verified: verify.verified,
      entries: verify.rows_checked,
      brokenEventId: brokenId
    };
    logsView.anchors = anchors.items.map((a) => ({
      seq: a.anchor_seq,
      auditHead: shortHash(a.audit_head),
      journalHead: shortHash(a.journal_head),
      anchoredAt: shortTs(a.anchored_at)
    }));
    logsView.error = null;
  } catch (e) {
    if (mine !== logsSeq) return;
    logsView.error = e.message ?? String(e);
    logsView.audit = [];
    logsView.verify = null;
    logsView.anchors = [];
  } finally {
    if (mine === logsSeq) logsView.loading = false;
  }
}
