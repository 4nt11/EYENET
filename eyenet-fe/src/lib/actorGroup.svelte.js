// Actor-groups (crews) workspace state. List from GET /v1/actor-groups — the
// connected components of the shared-infrastructure linkage graph (accounts that
// share contact handles / wallets / t.me links). Data-derived crews, not curated
// named threat actors. Svelte 5 runes.
import { apiGet, apiPost } from './api.js';

// Pretty-print an indicator token ("handle:wbpay" -> "@wbpay").
export function prettyInfra(tok) {
  if (!tok) return tok;
  if (tok.startsWith('handle:')) return '@' + tok.slice(7);
  if (tok.startsWith('tme:')) return 't.me/' + tok.slice(4);
  if (tok.startsWith('wallet_trx:')) return 'TRX ' + tok.slice(11);
  if (tok.startsWith('wallet_evm:')) return 'EVM ' + tok.slice(11);
  return tok;
}

function mapCrew(c, i) {
  const top = c.top_infra ?? [];
  const labelOf = new Map((c.members ?? []).map((m) => [m.actor_id, m.label]));
  const lbl = (id) => labelOf.get(id) ?? id.slice(0, 8);
  return {
    id: `crew-${i}`,
    size: c.size,
    members: c.members ?? [], // [{ actor_id, label }]
    topInfra: top,
    edgeCount: c.edge_count,
    maxScore: c.max_score,
    // The actual pairwise links behind edge_count, endpoints resolved to labels.
    links: (c.links ?? []).map((l) => ({
      a: lbl(l.actor_a_id),
      b: lbl(l.actor_b_id),
      aId: l.actor_a_id,
      bId: l.actor_b_id,
      score: l.score,
      shared: (l.shared ?? []).map(prettyInfra)
    })),
    // Name a nameless crew by its dominant shared infrastructure.
    name: top.length ? prettyInfra(top[0]) : `${c.size} accounts`
  };
}

export const actorGroupCtx = $state({ list: [], loaded: false, error: null });

// Promote a crew to a Case (POST /v1/actor-groups/case). Idempotent server-side
// on the crew key, so re-opening returns the same case. Tracks per-crew result.
export const crewCase = $state({ submitting: false, error: null, byId: {} });

// Linker-maintenance batch passes (POST /v1/linker/*, 202). run-infra rebuilds
// the shared_infra crews; detect-copypasta flags templated spam.
export const linkerRun = $state({ submitting: false, error: null, msg: null });

async function _runLinker(path, fmt) {
  linkerRun.submitting = true;
  linkerRun.error = null;
  linkerRun.msg = null;
  try {
    const res = await apiPost(path, {}, { auth: true, accept: [202] });
    linkerRun.msg = fmt(res);
    return res;
  } catch (e) {
    linkerRun.error = e.message ?? String(e);
    return null;
  } finally {
    linkerRun.submitting = false;
  }
}

export const runInfra = () =>
  _runLinker('/v1/linker/run-infra', (r) => `Proposed ${r.proposed} infra links.`);
export const detectCopypasta = () =>
  _runLinker('/v1/linker/detect-copypasta', (r) => `Flagged ${r.flagged} copypasta templates.`);

// Auto-open cases for all big, high-confidence crews (POST .../sweep-cases, 202).
export const crewSweep = $state({ submitting: false, error: null, opened: null });

export async function sweepCases() {
  crewSweep.submitting = true;
  crewSweep.error = null;
  crewSweep.opened = null;
  try {
    const res = await apiPost('/v1/actor-groups/sweep-cases', {}, { auth: true, accept: [202] });
    crewSweep.opened = res.opened;
    return res.opened;
  } catch (e) {
    crewSweep.error = e.message ?? String(e);
    return null;
  } finally {
    crewSweep.submitting = false;
  }
}

export async function openCase(crew) {
  crewCase.submitting = true;
  crewCase.error = null;
  try {
    const res = await apiPost(
      '/v1/actor-groups/case',
      { members: crew.members.map((m) => m.actor_id), top_infra: crew.topInfra },
      { auth: true }
    );
    crewCase.byId = { ...crewCase.byId, [crew.id]: res.case_id };
    return res.case_id;
  } catch (e) {
    crewCase.error = e.message ?? String(e);
    return null;
  } finally {
    crewCase.submitting = false;
  }
}

export async function loadActorGroups() {
  try {
    const res = await apiGet('/v1/actor-groups', { auth: true });
    actorGroupCtx.list = (res.items ?? []).map(mapCrew);
    actorGroupCtx.error = null;
  } catch (e) {
    actorGroupCtx.error = e.message ?? String(e);
    actorGroupCtx.list = [];
  } finally {
    actorGroupCtx.loaded = true;
  }
}
