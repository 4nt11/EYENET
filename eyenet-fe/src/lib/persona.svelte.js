// Personas workspace state. List from GET /v1/personas; selecting one fetches
// GET /v1/personas/{id} + /members and resolves each member's handle (the
// members endpoint carries only actor UUIDs). Merge/split POST to the graph
// worker (202) with an Idempotency-Key, then poll for the applied change.
// Svelte 5 runes in a module, same shape as linkage.svelte.js.
import { apiGet, apiPost } from './api.js';

const short = (id) => (id ? id.slice(0, 8) : '');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function mapPersona(p) {
  return { id: p.persona_id, label: p.label, memberCount: p.member_count };
}

export const personaCtx = $state({ list: [], loaded: false, error: null });

export async function loadPersonas() {
  try {
    const page = await apiGet('/v1/personas?limit=200', { auth: true });
    personaCtx.list = page.items.map(mapPersona);
    personaCtx.error = null;
  } catch (e) {
    personaCtx.error = e.message ?? String(e);
    personaCtx.list = [];
  } finally {
    personaCtx.loaded = true;
  }
}

export const personaView = $state({
  id: null,
  label: null,
  memberCount: 0,
  createdAt: null,
  updatedAt: null,
  members: [],
  loading: false,
  error: null,
  submitting: false,
  submitMsg: null
});

// No actor directory beyond per-id fetch; resolve a handle or fall back to the
// short UUID. A 404 (unknown actor) is expected — swallow to the short-id path.
async function actorHandle(actorId) {
  try {
    const a = await apiGet(`/v1/actors/${actorId}`, { auth: true });
    return a.primary_handle ?? null;
  } catch {
    return null;
  }
}

let detailSeq = 0;

export async function loadPersonaDetail(id) {
  const mine = ++detailSeq;
  personaView.loading = true;
  personaView.id = id;
  // Clear stale detail immediately so a fast row switch never shows the prior
  // persona's members while the new fetch is in flight.
  personaView.label = null;
  personaView.members = [];
  personaView.error = null;
  personaView.submitMsg = null;
  try {
    const [detail, membersPage] = await Promise.all([
      apiGet(`/v1/personas/${id}`, { auth: true }),
      apiGet(`/v1/personas/${id}/members`, { auth: true })
    ]);
    if (mine !== detailSeq) return; // superseded by a newer selection
    const rows = membersPage.items ?? [];
    const handles = await Promise.all(rows.map((m) => actorHandle(m.actor_id)));
    if (mine !== detailSeq) return;
    personaView.label = detail.label;
    personaView.memberCount = detail.member_count;
    personaView.createdAt = shortTs(detail.created_at);
    personaView.updatedAt = shortTs(detail.updated_at);
    personaView.members = rows.map((m, i) => ({
      actorId: m.actor_id,
      handle: handles[i] ?? short(m.actor_id),
      since: shortTs(m.since),
      viaLinkageId: m.via_linkage_id ? short(m.via_linkage_id) : 'seed'
    }));
    personaView.error = null;
  } catch (e) {
    if (mine !== detailSeq) return;
    personaView.error = e.message ?? String(e);
    personaView.members = [];
  } finally {
    if (mine === detailSeq) personaView.loading = false;
  }
}

// Merge/split are 202 — the graph worker applies the union-find mutation off the
// bus, so the persona doesn't change on the response. Poll GET /v1/personas/{id}
// (the WriteAccepted.poll target) briefly for a member_count/updated_at flip,
// then refresh, and say so honestly if the worker hasn't caught up.
async function _writeAndPoll(id, path, body, label) {
  personaView.submitting = true;
  personaView.submitMsg = null;
  const before = await apiGet(`/v1/personas/${id}`, { auth: true }).catch(() => null);
  try {
    await apiPost(path, body, {
      auth: true,
      headers: { 'Idempotency-Key': crypto.randomUUID() }
    });
    personaView.submitMsg = `${label} submitted — applying…`;
    let applied = false;
    for (let i = 0; i < 10; i++) {
      await sleep(500);
      const cur = await apiGet(`/v1/personas/${id}`, { auth: true }).catch(() => null);
      if (cur && before && (cur.updated_at !== before.updated_at || cur.member_count !== before.member_count)) {
        applied = true;
        break;
      }
    }
    await loadPersonas();
    if (personaView.id === id) await loadPersonaDetail(id);
    personaView.submitMsg = applied
      ? `${label} applied.`
      : `${label} submitted — pending apply (graph worker not caught up).`;
    return true;
  } catch (e) {
    personaView.submitMsg = `Failed: ${e.message ?? e}`;
    return false;
  } finally {
    personaView.submitting = false;
  }
}

export async function mergePersona(id, otherPersonaId, reason, caseRefs) {
  return _writeAndPoll(
    id,
    `/v1/personas/${id}/merge`,
    { other_persona_id: otherPersonaId, reason, case_refs: caseRefs ?? [] },
    'Merge'
  );
}

export async function splitPersona(id, actorId, reason, caseRefs) {
  return _writeAndPoll(
    id,
    `/v1/personas/${id}/split`,
    { actor_id: actorId, reason, case_refs: caseRefs ?? [] },
    'Split'
  );
}
