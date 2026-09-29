<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { apiGet } from '$lib/api.js';

  // Thread list for a forum category (GroupKind.FORUM_CATEGORY). Each thread
  // opens to its posts. Only forums have this layer; chats skip straight to messages.
  let threads = $state([]);
  let error = $state(null);
  let loaded = $state(false);
  const id = $derived($page.params.id);

  onMount(async () => {
    try {
      const p = await apiGet(`/v1/groups/${$page.params.id}/threads?limit=200`, { auth: true });
      threads = p.items ?? [];
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  });

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '—');
</script>

<main>
  <div class="head">
    <div class="crumb">
      <a class="slug-link" href="/reader">reader</a><span class="sep">/</span><span class="slug">category</span>
    </div>
    <h1>Threads</h1>
  </div>

  <div class="body">
    {#if !loaded}
      <p class="pnote">Loading…</p>
    {:else if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if !threads.length}
      <p class="pnote">No threads discovered in this category yet. The collector fills these as it crawls (paced).</p>
    {:else}
      <ul class="rows">
        {#each threads as t}
          <li>
            <a class="row" href={`/reader/group/${t.group_id}`}>
              <span class="title">{t.title || t.platform_groupid}</span>
              <span class="meta">tid {t.platform_groupid} · {fmt(t.last_observed_at)}</span>
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
  .slug-link { color: var(--text-secondary); text-decoration: none; }
  .slug-link:hover { color: var(--accent); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 12px 24px 24px; }
  .rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .row { display: flex; flex-direction: column; gap: 2px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; text-decoration: none; }
  .row:hover { border-color: var(--accent); }
  .title { color: var(--text-body); font-size: var(--fs-14); word-break: break-word; }
  .meta { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
</style>
