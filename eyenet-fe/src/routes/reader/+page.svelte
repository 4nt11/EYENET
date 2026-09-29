<script>
  import { onMount } from 'svelte';
  import { apiGet } from '$lib/api.js';

  // General reader entry: every monitored conversation, any source. Forum
  // categories open to their thread list; chats/channels/rooms open straight to
  // messages. Reuses GET /v1/groups (monitored subset) — no reader-specific list.
  let groups = $state([]);
  let error = $state(null);
  let loaded = $state(false);

  onMount(async () => {
    try {
      const page = await apiGet('/v1/groups?limit=200', { auth: true });
      groups = (page.items ?? []).filter((g) => g.status === 'monitored' && g.group_id);
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  });

  const KIND = {
    forum_category: 'forum',
    forum_thread: 'thread',
    channel: 'channel',
    chat: 'chat',
    matrix_room: 'room'
  };
  const kindLabel = (k) => KIND[k] ?? k ?? '—';
  const href = (g) =>
    g.kind === 'forum_category' ? `/reader/category/${g.group_id}` : `/reader/group/${g.group_id}`;
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
      <ul class="cards">
        {#each groups as g}
          <li>
            <a class="card" href={href(g)}>
              <span class="kind">{kindLabel(g.kind)}</span>
              <span class="title">{g.title || g.platform_groupid}</span>
              <span class="pid">{g.platform_groupid}</span>
            </a>
          </li>
        {/each}
      </ul>
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
  .cards { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
  .card { display: flex; flex-direction: column; gap: 4px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px; text-decoration: none; }
  .card:hover { border-color: var(--accent); }
  .kind { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--accent); }
  .title { color: var(--text-body); font-size: var(--fs-14); word-break: break-word; }
  .pid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); word-break: break-all; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
  a { color: var(--accent); }
</style>
