// Actor-groups (crews) workspace state. List from GET /v1/actor-groups — the
// connected components of the shared-infrastructure linkage graph (accounts that
// share contact handles / wallets / t.me links). Data-derived crews, not curated
// named threat actors. Svelte 5 runes.
import { apiGet } from './api.js';

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
  return {
    id: `crew-${i}`,
    size: c.size,
    members: c.members ?? [], // [{ actor_id, label }]
    topInfra: top,
    edgeCount: c.edge_count,
    maxScore: c.max_score,
    // Name a nameless crew by its dominant shared infrastructure.
    name: top.length ? prettyInfra(top[0]) : `${c.size} accounts`
  };
}

export const actorGroupCtx = $state({ list: [], loaded: false, error: null });

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
