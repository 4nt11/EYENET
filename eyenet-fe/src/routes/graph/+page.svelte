<script>
  import StatTile from '$lib/components/StatTile.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import { graphSearch, searchActors } from '$lib/graph.svelte.js';

  let { data } = $props();

  const fmt = (n) => Number(n).toLocaleString('en-US');

  // Only backable tiles. Linkages is the TOTAL — the sum of the per-state
  // LinkageStateCounts. No Nodes / Edges / Sources tile: the API has no such
  // field. `tier` (row severity) is likewise dropped — not in the contract.
  let tiles = $derived(
    data.stats
      ? [
          { label: 'Actors', value: fmt(data.stats.actors) },
          { label: 'Personas', value: fmt(data.stats.personas), tone: 'accent' },
          {
            label: 'Linkages',
            value: fmt(Object.values(data.stats.linkages).reduce((a, b) => a + b, 0))
          },
          { label: 'Observations', value: fmt(data.stats.observations) }
        ]
      : []
  );

  // /v1/graph/stats + /v1/graph/search need read:graph. 401/403 = no token yet.
  const NOAUTH = new Set([401, 403]);

  // Search is actors-only and q is REQUIRED. Empty box → idle (fetch nothing).
  const ACTOR_COLUMNS = [
    { key: 'id', header: 'Actor', mono: true, width: '300px' },
    { key: 'handle', header: 'Handle', mono: true },
    { key: 'platforms', header: 'Platforms', mono: true, width: '160px' },
    { key: 'score', header: 'Score', mono: true, align: 'right', width: '90px' }
  ];

  let q = $state('');
  // Debounce keystrokes into the search store.
  let timer;
  $effect(() => {
    const term = q;
    clearTimeout(timer);
    timer = setTimeout(() => searchActors(term), 200);
    return () => clearTimeout(timer);
  });
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">Investigate</span><span class="sep">/</span><span class="slug">graph</span></div>
      <h1>Graph</h1>
    </div>
    <input class="search" type="search" bind:value={q} placeholder="Search actors · handle, alias, identifier…" spellcheck="false" />
  </div>

  <div class="body">
    {#if data.stats}
      <div class="tiles">
        {#each tiles as s}
          <StatTile {...s} />
        {/each}
      </div>
    {:else if NOAUTH.has(data.statsStatus)}
      <p class="note">Graph stats need a token with <code>read:graph</code>. Sign in to view actors · personas · linkages · observations.</p>
    {:else}
      <p class="note">Graph stats unavailable (<code>/v1/graph/stats</code> did not respond).</p>
    {/if}

    <Panel title="Actor search" class="grow">
      {#snippet action()}
        {#if !graphSearch.idle && !graphSearch.loading && !graphSearch.error}
          <span class="count">{graphSearch.results.length} match{graphSearch.results.length === 1 ? '' : 'es'}</span>
        {/if}
      {/snippet}
      {#if graphSearch.idle}
        <div class="empty">Type a handle, alias, or identifier to search actors.</div>
      {:else if graphSearch.loading}
        <div class="empty">Searching…</div>
      {:else if graphSearch.error}
        <div class="empty">Search failed: <code>{graphSearch.error}</code></div>
      {:else if graphSearch.results.length}
        <DataTable rowKey="id" columns={ACTOR_COLUMNS} rows={graphSearch.results} />
      {:else}
        <div class="empty">No actors match <code>{q.trim()}</code>.</div>
      {/if}
    </Panel>

    <p class="footnote">Topology view (node-link canvas) needs a graph-traversal endpoint that
      doesn't exist yet · this category only exposes <code>stats</code> and <code>search</code>.</p>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { flex: 0 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group, .sep { color: var(--text-faint); }
  .group { text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }

  .search {
    width: 320px;
    max-width: 40vw;
    height: 30px;
    padding: 0 10px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius);
    color: var(--text-body);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    letter-spacing: var(--tracking-data);
  }
  .search::placeholder { color: var(--text-faint); }
  .search:focus { outline: none; border-color: var(--accent); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }
  :global(.panel.grow) { min-height: 160px; }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .empty { padding: 20px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }
  /* Boxed inline notice (stats unavailable / needs read:graph). */
  .note { margin: 0 0 16px; padding: 12px; border: 1px solid var(--border); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .note code { color: var(--accent-text); background: none; padding: 0; }
  /* Quiet unboxed footnote (no-topology-endpoint note). */
  .footnote { margin: 12px 0 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }
  .footnote code { color: var(--accent-text); }
  code { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-body); background: var(--surface); padding: 1px 5px; border-radius: var(--radius-sm); }
</style>
