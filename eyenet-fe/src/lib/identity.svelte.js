// Identity-pool workspace state. List from GET /v1/identities; selecting one
// fetches GET /v1/identities/{id} for cooldown/notes. Lifecycle actions
// (claim/release/freeze/burn + freeze_all) persist synchronously in the handler
// (the operator-under-attack invariant), so a reload shows the new state — no
// polling. Every action requires a reason (IdentityActionRequest).
import { apiGet, apiPost } from './api.js';

const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');

// state ∈ available|in_use|cooling|frozen|burned. in_use = purple (active),
// cooling = amber, burned = red, frozen/available = quiet.
const STATE_TONE = { in_use: 'high', cooling: 'warn', frozen: 'neutral', burned: 'critical', available: 'low' };
export const identityTone = (s) => STATE_TONE[s] ?? 'neutral';

function mapIdentity(i) {
  return {
    id: i.identity_id,
    name: i.name,
    sourceId: i.source_id,
    role: i.role,
    state: i.state,
    lastUsed: shortTs(i.last_used_at)
  };
}

export const identityCtx = $state({ list: [], loaded: false, error: null });

export async function loadIdentities() {
  try {
    const page = await apiGet('/v1/identities?limit=200', { auth: true });
    identityCtx.list = page.items.map(mapIdentity);
    identityCtx.error = null;
  } catch (e) {
    identityCtx.error = e.message ?? String(e);
    identityCtx.list = [];
  } finally {
    identityCtx.loaded = true;
  }
}

export const identityView = $state({
  id: null,
  cooldown: null,
  notes: null,
  loading: false,
  error: null,
  submitting: false,
  submitMsg: null
});

let detailSeq = 0;

export async function loadIdentityDetail(id) {
  const mine = ++detailSeq;
  identityView.loading = true;
  identityView.id = id;
  identityView.cooldown = null;
  identityView.notes = null;
  identityView.error = null;
  identityView.submitMsg = null;
  try {
    const d = await apiGet(`/v1/identities/${id}`, { auth: true });
    if (mine !== detailSeq) return;
    identityView.cooldown = d.cooldown_seconds;
    identityView.notes = d.notes;
    identityView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    identityView.error = e.message ?? String(e);
  } finally {
    if (mine === detailSeq) identityView.loading = false;
  }
}

async function _post(path, reason, note) {
  identityView.submitting = true;
  identityView.submitMsg = null;
  try {
    await apiPost(path, { reason, note: note || null }, {
      auth: true,
      headers: { 'Idempotency-Key': crypto.randomUUID() }
    });
    await loadIdentities(); // state is durable on return — reload reflects it
    return true;
  } catch (e) {
    identityView.submitMsg = `Failed: ${e.message ?? e}`;
    return false;
  } finally {
    identityView.submitting = false;
  }
}

// action ∈ claim | release | freeze | burn
export async function identityAction(id, action, reason, note) {
  if (await _post(`/v1/identities/${id}/${action}`, reason, note)) {
    identityView.submitMsg = `${action} applied.`;
  }
}

export async function freezeAll(reason) {
  if (await _post('/v1/identities/freeze_all', reason)) {
    identityView.submitMsg = 'freeze-all applied.';
  }
}
