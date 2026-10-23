// Monitored-groups workspace state. List from GET /v1/groups (a source-agnostic
// view over GroupCandidate: joined + discovered + dialog-seen). "Join at will"
// POSTs /v1/groups/join (202; the supervisor executes the join off-path, so the
// row flips to joining then monitored on a later reload). "Rescan" POSTs
// /v1/groups/scan to refresh visibility from running collectors. Svelte 5 runes.
import { apiGet, apiPost } from './api.js';
import { realPlatform, foundVia } from './discovery-shape.js';

const short = (id) => (id ? id.slice(0, 8) : '—');
const shortTs = (ts) => (ts ? ts.replace('T', ' ').replace(/\..*$/, 'Z') : '·');

// Derived status (see GroupSummary._status server-side).
const TONE = {
  monitored: 'high',
  joining: 'warn',
  requested: 'accent',
  approving: 'warn',
  member_unmonitored: 'accent',
  discovered: 'neutral',
  rejected: 'critical',
  failed: 'critical',
  parked: 'low'
};
export const groupStatusTone = (s) => TONE[s] ?? 'neutral';

// Statuses from which an operator can start a join.
const JOINABLE = new Set(['discovered', 'member_unmonitored', 'parked']);
export const isJoinable = (s) => JOINABLE.has(s);

function mapGroup(g) {
  return {
    id: g.candidate_id,
    sourceId: g.source_id,
    title: g.title || g.platform_groupid,
    platformGroupId: g.platform_groupid,
    kind: g.kind ?? '',
    status: g.status,
    // The candidate's REAL platform (from its shape), not the observing source's
    // — a @handle found on a forum is a telegram lead, not a forum group.
    realPlatform: realPlatform(g.platform_groupid, g.kind),
    foundVia: foundVia(g.platform_groupid, g.kind, g.member_dialog),
    memberDialog: g.member_dialog,
    score: g.score,
    groupId: g.group_id,
    lastSeen: shortTs(g.last_observed_at_ingest)
  };
}

export const GROUP_PAGE_SIZE = 200; // rows per page; raise it to trade DOM weight for fewer pages

// One server page at a time. `page` is the 0-based page index, `total` the
// estimated row count over the current server filter (for the page count).
export const groupCtx = $state({ list: [], loaded: false, error: null, page: 0, total: null });

// The API cursor is an opaque base64url of the integer offset (deps_paging.py),
// so page N == cursor(N * PAGE_SIZE). Encoding it here lets us jump to any page.
// ponytail: couples to the offset cursor format; if the API ever switches to
// keyset, swap this for a real page/offset query param.
const cursorFor = (offset) =>
  offset <= 0 ? null : btoa(String(offset)).replace(/\+/g, '-').replace(/\//g, '_');

// Server-side narrowing: substring search (name + platform id), source, dialog
// membership (memberDialog), and lifecycle state (e.g. 'joined' for monitored).
// All axes are server-side so numbered pages + the total stay coherent.
// estimated_total comes back for the page count.
export async function loadGroups(
  search = '', sourceId = '', { page = 0, memberDialog = null, state = '' } = {}
) {
  try {
    const params = new URLSearchParams({ limit: String(GROUP_PAGE_SIZE), include_total: '1' });
    if (search.trim()) params.set('q', search.trim());
    if (sourceId) params.set('source_id', sourceId);
    if (state) params.set('state', state);
    if (memberDialog !== null) params.set('member_dialog', memberDialog ? 'true' : 'false');
    const c = cursorFor(page * GROUP_PAGE_SIZE);
    if (c) params.set('cursor', c);
    const res = await apiGet(`/v1/groups?${params}`, { auth: true });
    groupCtx.list = res.items.map(mapGroup);
    groupCtx.page = page;
    groupCtx.total = res.estimated_total ?? null;
    groupCtx.error = null;
  } catch (e) {
    groupCtx.error = e.message ?? String(e);
    groupCtx.list = [];
    groupCtx.total = null;
  } finally {
    groupCtx.loaded = true;
  }
}

export const groupView = $state({ submitting: false, submitMsg: null });

export async function joinGroup(candidateId, collectorId, backfill = true) {
  groupView.submitting = true;
  groupView.submitMsg = null;
  try {
    await apiPost(
      '/v1/groups/join',
      { candidate_id: candidateId, collector_id: collectorId, backfill },
      { auth: true, accept: [202] }
    );
    groupView.submitMsg = backfill
      ? 'Join requested — the collector will join and backfill history off-path.'
      : 'Join requested — the collector will join off-path (no backfill).';
    await loadGroups();
  } catch (e) {
    groupView.submitMsg = `Failed: ${e.message ?? e}`;
  } finally {
    groupView.submitting = false;
  }
}

export async function leaveGroup(candidateId, reason) {
  groupView.submitting = true;
  groupView.submitMsg = null;
  try {
    await apiPost(
      '/v1/groups/leave',
      { candidate_id: candidateId, reason: reason || 'operator_left' },
      { auth: true, accept: [202] }
    );
    groupView.submitMsg = 'Leave requested — the collector departs off-path.';
    await loadGroups();
  } catch (e) {
    groupView.submitMsg = `Failed: ${e.message ?? e}`;
  } finally {
    groupView.submitting = false;
  }
}

// --- stealer-channel collection class (category == 'stealer_logs') ---------
// GET /v1/stealer/channels (read:stealer) is the set of group ids marked as
// stealer-log drop sources; marking POSTs /v1/groups/{id}/category (admin:stealer).
// Marking lifts the channel past the collector's attachment size cap so the
// multi-GB archive drops are captured. Kept as a flat id list the page tests
// membership against — the GET /v1/groups candidate view carries no category.
export const stealerCtx = $state({ ids: [], loaded: false });

export async function loadStealerChannels() {
  try {
    const rows = await apiGet('/v1/stealer/channels', { auth: true });
    stealerCtx.ids = rows.map((r) => r.group_id);
  } catch {
    // 403 (no read:stealer) or error — just show nothing marked, don't break the page.
    stealerCtx.ids = [];
  } finally {
    stealerCtx.loaded = true;
  }
}

export async function markStealer(groupId, on) {
  groupView.submitting = true;
  groupView.submitMsg = null;
  try {
    await apiPost(`/v1/groups/${groupId}/category`, { category: on ? 'stealer_logs' : null }, { auth: true });
    stealerCtx.ids = on
      ? [...new Set([...stealerCtx.ids, groupId])]
      : stealerCtx.ids.filter((id) => id !== groupId);
    groupView.submitMsg = on
      ? 'Marked as stealer channel — the collector bypasses the attachment size cap here.'
      : 'Unmarked — the attachment size cap re-applies.';
  } catch (e) {
    groupView.submitMsg = `Failed: ${e.message ?? e}`;
  } finally {
    groupView.submitting = false;
  }
}

export async function scanGroups() {
  groupView.submitting = true;
  groupView.submitMsg = null;
  try {
    const r = await apiPost('/v1/groups/scan', {}, { auth: true, accept: [202] });
    groupView.submitMsg = `Scan sent to ${r.collectors_signaled} collector(s); refreshing…`;
    setTimeout(loadGroups, 1500); // give collectors a moment to enumerate + upsert
  } catch (e) {
    groupView.submitMsg = `Failed: ${e.message ?? e}`;
  } finally {
    groupView.submitting = false;
  }
}

export { short };
