<script>
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api.js';
  import { GROUP_KIND_LABELS } from '$lib/labels.js';

  // General reader entry: every monitored conversation, any source. Forum
  // categories open to their thread list; chats/channels/rooms open straight to
  // messages. Reuses GET /v1/groups (monitored subset) — no reader-specific list.
  let groups = $state([]);
  let error = $state(null);
  let loaded = $state(false);

  onMount(async () => {
    try {
      // Filter to monitored groups at the API (discovery floods the list with
      // discovered candidates that would otherwise bury the readable ones), and
      // page through the cursor so nothing is truncated at a fixed limit.
      const all = [];
      let cursor = null;
      for (let i = 0; i < 50; i++) {
        const q = cursor
          ? `?status=monitored&limit=500&cursor=${encodeURIComponent(cursor)}`
          : '?status=monitored&limit=500';
        const page = await apiGet(`/v1/groups${q}`, { auth: true });
        all.push(...(page.items ?? []));
        cursor = page.next_cursor;
        if (!cursor) break;
      }
      groups = all.filter((g) => g.group_id);
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  });

  const kindLabel = (k) => GROUP_KIND_LABELS[k] ?? k ?? '—';
  const href = (g) =>
    g.kind === 'forum_category' ? `/reader/category/${g.group_id}` : `/reader/group/${g.group_id}`;

  // Compact display of a forum URL: drop scheme + trailing slash, and collapse a
  // 56-char v3 onion host to a readable stub (full URL stays in the title attr).
  const shortUrl = (u) => {
    if (!u) return null;
    const s = u.replace(/^https?:\/\//, '').replace(/\/+$/, '');
    const m = s.match(/^([a-z2-7]{56})(\.onion.*)$/i);
    return m ? `${m[1].slice(0, 10)}…${m[2]}` : s;
  };

  // One section per source: group on source_id (always present), label it with the
  // forum host / source label, sort sections by that label and cards by title.
  const sourceName = (g) => shortUrl(g.source_url) || g.source_label || g.source_id;
  const sections = $derived.by(() => {
    const by = new Map();
    for (const g of groups) {
      const s = by.get(g.source_id) ?? { id: g.source_id, name: sourceName(g), items: [] };
      s.items.push(g);
      by.set(g.source_id, s);
    }
    const out = [...by.values()];
    for (const s of out)
      s.items.sort((a, b) => (a.title || a.platform_groupid).localeCompare(b.title || b.platform_groupid));
    out.sort((a, b) => a.name.localeCompare(b.name));
    return out;
  });
</script>

<main>
  <div class="head">
    <div class="crumb"><span class="group">Investigate</span><span class="sep">/</span><span class="slug">reader</span></div>
    <h1>Reader</h1>
    <p class="desc">Reconstruct monitored conversations. Forum categories open to their threads; chats and channels open to their messages.</p>
  </div>

  <div class="body">
    {#if !loaded}
      <p class="pnote">Loading…</p>
    {:else if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if !groups.length}
      <p class="pnote">Nothing monitored yet. Monitor a forum category or a chat in <a href="/monitored-groups">Monitored groups</a>.</p>
    {:else}
      {#each sections as s (s.id)}
        <section class="src-group">
          <h2 class="src-head" title={s.name}>{s.name}<span class="count">{s.items.length}</span></h2>
          <ul class="cards">
            {#each s.items as g (g.group_id)}
              <li>
                <a class="card" href={href(g)}>
                  <span class="kind">{kindLabel(g.kind)}</span>
                  <span class="title">{g.title || g.platform_groupid}</span>
                  <span class="pid">{g.platform_groupid}</span>
                </a>
              </li>
            {/each}
          </ul>
        </section>
      {/each}
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { padding: 20px 24px 0; }
  .crumb { display: flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .crumb .sep { color: var(--text-faint); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); }
  .desc { color: var(--text-secondary); font-size: var(--fs-13); max-width: 70ch; }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 8px 24px 24px; }
  .cards { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; align-items: stretch; }
  .cards > li { display: flex; min-width: 0; }
  /* height:100% so a card fills its grid cell — otherwise a tall neighbour (a 2-line
     title) stretches the row and the shorter cards leave dead space below them. */
  .card { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; text-decoration: none; }
  .card:hover { border-color: var(--accent); }
  .kind { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--accent); }
  /* clamp to 2 lines so titles don't swing card heights wildly (full text in the link) */
  .title { color: var(--text-body); font-size: var(--fs-14); word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .pid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); word-break: break-all; }
  .src-group { margin: 0 0 22px; }
  /* sticky source header so the group you're scrolling stays labelled; brighter
     than --accent so the source (forum host / telegram:name / discord) pops */
  .src-head { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; gap: 8px; margin: 0 0 8px; padding: 6px 0; background: var(--black); font-family: var(--font-mono); font-size: var(--fs-13); color: #c88bff; word-break: break-all; }
  .src-head .count { font-size: var(--fs-11); color: var(--text-faint); background: var(--panel); border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
  a { color: var(--accent); }
</style>
