// Manual (operator-curated) crews: persistent, hand-built actor groups, distinct
// from the derived /actor-groups crews. CRUD against /v1/crews. Svelte 5 runes.
import { apiGet, apiPost, apiDelete } from './api.js';

const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '');

export const manualCrewCtx = $state({ list: [], loaded: false, error: null });

export async function loadManualCrews() {
  try {
    const page = await apiGet('/v1/crews', { auth: true });
    manualCrewCtx.list = (page.items ?? []).map((c) => ({
      id: c.crew_id,
      name: c.name,
      notes: c.notes ?? '',
      memberCount: c.member_count,
      updatedAt: shortTs(c.updated_at)
    }));
    manualCrewCtx.error = null;
  } catch (e) {
    manualCrewCtx.error = e.message ?? String(e);
    manualCrewCtx.list = [];
  } finally {
    manualCrewCtx.loaded = true;
  }
}

export const manualCrewView = $state({
  id: null,
  detail: null, // { name, notes, members: [{actor_id, handle, displayName}] }
  loading: false,
  error: null,
  busy: false,
  msg: null
});

function _applyDetail(d) {
  manualCrewView.detail = {
    name: d.name,
    notes: d.notes ?? '',
    createdAt: shortTs(d.created_at),
    members: (d.members ?? []).map((m) => ({
      actor_id: m.actor_id,
      handle: m.handle || m.actor_id.slice(0, 8),
      displayName: m.display_name ?? ''
    }))
  };
}

let detailSeq = 0;

export async function loadManualCrewDetail(id) {
  const mine = ++detailSeq;
  manualCrewView.loading = true;
  manualCrewView.id = id;
  manualCrewView.detail = null;
  manualCrewView.error = null;
  manualCrewView.msg = null;
  try {
    const d = await apiGet(`/v1/crews/${id}`, { auth: true });
    if (mine !== detailSeq) return;
    _applyDetail(d);
    manualCrewView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    manualCrewView.error = e.message ?? String(e);
  } finally {
    if (mine === detailSeq) manualCrewView.loading = false;
  }
}

export async function createCrew(name, notes) {
  const res = await apiPost('/v1/crews', { name, notes: notes || null }, { auth: true, accept: [201] });
  await loadManualCrews();
  return res.crew_id;
}

// Add by @handle (resolved server-side). Returns true on success.
export async function addMember(crewId, handle) {
  manualCrewView.busy = true;
  manualCrewView.msg = null;
  try {
    const d = await apiPost(`/v1/crews/${crewId}/members`, { handle }, { auth: true });
    _applyDetail(d);
    await loadManualCrews(); // refresh member counts
    return true;
  } catch (e) {
    manualCrewView.msg = e.status === 404 ? `No actor for ${handle}` : `Failed: ${e.message ?? e}`;
    return false;
  } finally {
    manualCrewView.busy = false;
  }
}

export async function removeMember(crewId, actorId) {
  manualCrewView.busy = true;
  try {
    const d = await apiDelete(`/v1/crews/${crewId}/members/${actorId}`, { auth: true });
    _applyDetail(d);
    await loadManualCrews();
  } catch (e) {
    manualCrewView.msg = `Failed: ${e.message ?? e}`;
  } finally {
    manualCrewView.busy = false;
  }
}

export async function deleteCrew(crewId) {
  await apiDelete(`/v1/crews/${crewId}`, { auth: true });
  manualCrewView.detail = null;
  manualCrewView.id = null;
  await loadManualCrews();
}
