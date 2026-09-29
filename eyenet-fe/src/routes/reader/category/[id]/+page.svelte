<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { apiGet } from '$lib/api.js';

  // Thread list for a forum category (GroupKind.FORUM_CATEGORY). Each thread
  // opens to its posts. Only forums have this layer; chats skip straight to messages.
  // A search box flips this to a cross-thread body search: find a post anywhere in
  // the category without opening each thread (GET .../search?q=), scoped to THIS category.
  let threads = $state([]);
  let error = $state(null);
  let loaded = $state(false);
  let search = $state('');
  let hits = $state([]); // cross-thread search results (each carries its thread)
  let total = $state(null);
  let searching = $state(false);
  let searchTimer;
  const searchMode = $derived(search.trim().length > 0);

  onMount(async () => {
    try {
      const p = await apiGet(`/v1/groups/${$page.params.id}/threads?limit=200`, { auth: true });
      threads = p.items ?? [];
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  });

  async function runSearch() {
    const q = search.trim();
    if (!q) {
      hits = [];
      total = null;
      return;
    }
    searching = true;
    error = null;
    try {
      const params = new URLSearchParams({ q, limit: '200', include_total: '1' });
      const p = await apiGet(`/v1/groups/${$page.params.id}/search?${params}`, { auth: true });
      hits = p.items ?? [];
      total = p.estimated_total ?? null;
    } catch (e) {
      error = e.message;
    }
    searching = false;
  }

  // Debounce keystrokes: one request 250ms after the operator stops typing.
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 250);
  }

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '—');
  const snippet = (b) => (b ?? '').replace(/\s+/g, ' ').slice(0, 140);
</script>

<main>
  <div class="head">
    <div class="crumb">
      <a class="slug-link" href="/reader">reader</a><span class="sep">/</span><span class="slug">category</span>
    </div>
    <h1>Threads</h1>
    <div class="searchrow">
      <input
        class="search"
        type="search"
        placeholder="Search every thread in this category…"
        bind:value={search}
        oninput={onSearch}
        aria-label="Search message bodies across this category's threads" />
      {#if searchMode && !searching}
        <span class="scount">
          {hits.length}{#if total != null && total > hits.length}<span class="oftotal"> / {total}</span>{/if}
          match{(total ?? hits.length) === 1 ? '' : 'es'}
        </span>
      {/if}
    </div>
  </div>

  <div class="body">
    {#if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if searchMode}
      {#if searching}
        <p class="pnote">Searching…</p>
      {:else if !hits.length}
        <p class="pnote">No posts in this category match “{search.trim()}”.</p>
      {:else}
        <ul class="rows">
          {#each hits as h}
            <li>
              <a class="row" href={`/reader/group/${h.thread_group_id}`}>
                <span class="title">{snippet(h.body)}</span>
                <span class="meta">in {h.thread_title || h.thread_group_id.slice(0, 8)} · {h.author_display || 'unknown'} · {fmt(h.ts)}</span>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    {:else if !loaded}
      <p class="pnote">Loading…</p>
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
  .searchrow { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
  .search { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; min-width: 280px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .scount { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); white-space: nowrap; }
  .oftotal { color: var(--text-muted); }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 12px 24px 24px; }
  .rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .row { display: flex; flex-direction: column; gap: 2px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; text-decoration: none; }
  .row:hover { border-color: var(--accent); }
  .title { color: var(--text-body); font-size: var(--fs-14); word-break: break-word; }
  .meta { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
</style>
