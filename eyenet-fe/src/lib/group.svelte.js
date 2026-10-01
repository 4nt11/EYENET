// Monitored-groups workspace state. List from GET /v1/groups (a source-agnostic
// view over GroupCandidate: joined + discovered + dialog-seen). "Join at will"
// POSTs /v1/groups/join (202; the supervisor executes the join off-path, so the
// row flips to joining then monitored on a later reload). "Rescan" POSTs
// /v1/groups/scan to refresh visibility from running collectors. Svelte 5 runes.
import { apiGet, apiPost } from './api.js';

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
    memberDialog: g.member_dialog,
    score: g.score,
    groupId: g.group_id,
    lastSeen: shortTs(g.last_observed_at_ingest)
  };
}

export const groupCtx = $state({ list: [], loaded: false, error: null });

export async function loadGroups(search = '', sourceId = '') {
  try {
    // Server-side substring search (name + platform id) + source filter cut
    // through the discovery firehose. Page through the opaque cursor so a source
    // with >500 groups isn't silently truncated (the old fixed limit=200 was).
    const base = new URLSearchParams({ limit: '500' });
    if (search.trim()) base.set('q', search.trim());
    if (sourceId) base.set('source_id', sourceId);
    const all = [];
    let cursor = null;
    for (let i = 0; i < 50; i++) {
      const params = new URLSearchParams(base);
      if (cursor) params.set('cursor', cursor);
      const page = await apiGet(`/v1/groups?${params}`, { auth: true });
      all.push(...page.items);
      cursor = page.next_cursor;
      if (!cursor) break;
    }
    groupCtx.list = all.map(mapGroup);
    groupCtx.error = null;
  } catch (e) {
    groupCtx.error = e.message ?? String(e);
    groupCtx.list = [];
  } finally {
    groupCtx.loaded = true;
  }
}

export const groupView = $state({ submitting: false, submitMsg: null });

export async function joinGroup(candidateId, collectorId) {
  groupView.submitting = true;
  groupView.submitMsg = null;
  try {
    await apiPost(
      '/v1/groups/join',
      { candidate_id: candidateId, collector_id: collectorId },
      { auth: true, accept: [202] }
    );
    groupView.submitMsg = 'Join requested — the collector will join off-path.';
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
