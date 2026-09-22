// Collector-fleet workspace state. List from GET /v1/collectors + fleet counts
// from GET /v1/collectors/health; selecting one fetches GET /v1/collectors/{id}
// (identity, last error) and /{id}/memberships (active-group count — the list
// carries no count). Start/stop/delete are supervisor-reconciled writes.
import { apiGet, apiPost, apiDelete } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '—');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// observed_state ∈ stopped|starting|running|cooling|crashed. Badge tone: live
// = purple, transitional = amber, crashed = red, stopped = quiet.
const OBSERVED_TONE = { running: 'high', starting: 'warn', cooling: 'warn', crashed: 'critical', stopped: 'low' };
export const observedTone = (s) => OBSERVED_TONE[s] ?? 'neutral';

function mapCollector(c) {
  return {
    id: c.collector_id,
    name: c.instance_name,
    kind: c.kind,
    desired: c.desired_state,
    observed: c.observed_state,
    restartCount: c.restart_count,
    heartbeat: shortTs(c.last_heartbeat_at)
  };
}

export const collectorCtx = $state({ list: [], fleet: null, loaded: false, error: null });

export async function loadCollectors() {
  try {
    const [page, health] = await Promise.all([
      apiGet('/v1/collectors?limit=200', { auth: true }),
      apiGet('/v1/collectors/health', { auth: true })
    ]);
    collectorCtx.list = page.items.map(mapCollector);
    collectorCtx.fleet = health; // {total, counts_by_observed_state, ...}
    collectorCtx.error = null;
  } catch (e) {
    collectorCtx.error = e.message ?? String(e);
    collectorCtx.list = [];
    collectorCtx.fleet = null;
  } finally {
    collectorCtx.loaded = true;
  }
}

export const collectorView = $state({
  id: null,
  identity: '—',
  groups: 0,
  lastError: null,
  loading: false,
  error: null,
  submitting: false,
  submitMsg: null
});

let detailSeq = 0;

export async function loadCollectorDetail(id) {
  const mine = ++detailSeq;
  collectorView.loading = true;
  collectorView.id = id;
  collectorView.identity = '—';
  collectorView.groups = 0;
  collectorView.lastError = null;
  collectorView.error = null;
  collectorView.submitMsg = null;
  try {
    const [detail, memberships] = await Promise.all([
      apiGet(`/v1/collectors/${id}`, { auth: true }),
      apiGet(`/v1/collectors/${id}/memberships`, { auth: true })
    ]);
    if (mine !== detailSeq) return;
    const rows = Array.isArray(memberships) ? memberships : (memberships.items ?? []);
    collectorView.identity = short(detail.identity_id);
    collectorView.groups = rows.filter((m) => m.left_at == null).length;
    collectorView.lastError = detail.last_error_message ?? null;
    collectorView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    collectorView.error = e.message ?? String(e);
  } finally {
    if (mine === detailSeq) collectorView.loading = false;
  }
}

// Create-collector form state. Sources/identities feed the two selects; the
// create leases the chosen identity (one collector per identity), so a reused
// identity or a duplicate instance_name comes back 409 and is surfaced.
export const collectorCreate = $state({ submitting: false, error: null, ok: null });

// payload: {instance_name, kind, source_id, identity_id, config, notes}.
// Returns true on success (so the caller can close the dialog).
export async function createCollector(payload) {
  collectorCreate.submitting = true;
  collectorCreate.error = null;
  collectorCreate.ok = null;
  try {
    const row = await apiPost('/v1/collectors', payload, { auth: true });
    collectorCreate.ok = `created ${row.instance_name}.`;
    await loadCollectors();
    return true;
  } catch (e) {
    collectorCreate.error = e.message ?? String(e);
    return false;
  } finally {
    collectorCreate.submitting = false;
  }
}

// action ∈ 'start' | 'stop' | 'delete'. start/stop are 202 — the supervisor
// reconciles observed_state → desired asynchronously, so we poll for the flip
// and message honestly if no supervisor is running. delete needs observed
// STOPPED server-side (409 otherwise → surfaced).
export async function collectorAction(id, action) {
  collectorView.submitting = true;
  collectorView.submitMsg = null;
  const before = collectorCtx.list.find((c) => c.id === id)?.observed;
  try {
    if (action === 'delete') {
      await apiDelete(`/v1/collectors/${id}`, { auth: true });
      collectorView.submitMsg = 'deleted.';
      await loadCollectors();
      return;
    }
    await apiPost(`/v1/collectors/${id}/${action}`, {}, { auth: true });
    collectorView.submitMsg = `${action} requested — supervisor reconciling…`;
    let changed = false;
    for (let i = 0; i < 10; i++) {
      await sleep(500);
      const c = await apiGet(`/v1/collectors/${id}`, { auth: true });
      if (c.observed_state !== before) {
        changed = true;
        break;
      }
    }
    await loadCollectors();
    collectorView.submitMsg = changed
      ? `${action} applied.`
      : `${action} requested — pending (no supervisor caught up).`;
  } catch (e) {
    collectorView.submitMsg = `Failed: ${e.message ?? e}`;
  } finally {
    collectorView.submitting = false;
  }
}
