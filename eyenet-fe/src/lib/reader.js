// Shared Reader helpers: the paged monitored-groups fetch + the per-card display
// bits, used by the source landing (/reader) and a single source (/reader/source/[id]).
import { apiGet } from '$lib/api.js';
import { GROUP_KIND_LABELS } from '$lib/labels.js';

// Every monitored group, optionally narrowed to one source at the API. Pages the
// opaque cursor so a source with >500 groups is never silently truncated.
export async function fetchMonitored(sourceId = '') {
  const base = new URLSearchParams({ status: 'monitored', limit: '500' });
  if (sourceId) base.set('source_id', sourceId);
  const all = [];
  let cursor = null;
  for (let i = 0; i < 50; i++) {
    const params = new URLSearchParams(base);
    if (cursor) params.set('cursor', cursor);
    const page = await apiGet(`/v1/groups?${params}`, { auth: true });
    all.push(...(page.items ?? []));
    cursor = page.next_cursor;
    if (!cursor) break;
  }
  return all.filter((g) => g.group_id);
}

export const kindLabel = (k) => GROUP_KIND_LABELS[k] ?? k ?? '—';

export const groupHref = (g) =>
  g.kind === 'forum_category' ? `/reader/category/${g.group_id}` : `/reader/group/${g.group_id}`;

// Compact display of a forum URL: drop scheme + trailing slash, and collapse a
// 56-char v3 onion host to a readable stub (full URL stays in a title attr).
export function shortUrl(u) {
  if (!u) return null;
  const s = u.replace(/^https?:\/\//, '').replace(/\/+$/, '');
  const m = s.match(/^([a-z2-7]{56})(\.onion.*)$/i);
  return m ? `${m[1].slice(0, 10)}…${m[2]}` : s;
}

// A source's display name: forum host / telegram:name / discord, else the id.
export const sourceName = (g) => shortUrl(g.source_url) || g.source_label || g.source_id;

// Fold a monitored-group list into one entry per source, sorted by name, each
// carrying its group list (sorted by title). Used by the source landing.
export function bySource(groups) {
  const by = new Map();
  for (const g of groups) {
    const s = by.get(g.source_id) ?? { id: g.source_id, name: sourceName(g), items: [] };
    s.items.push(g);
    by.set(g.source_id, s);
  }
  const out = [...by.values()];
  const title = (g) => g.title || g.platform_groupid;
  for (const s of out) s.items.sort((a, b) => title(a).localeCompare(title(b)));
  out.sort((a, b) => a.name.localeCompare(b.name));
  return out;
}
