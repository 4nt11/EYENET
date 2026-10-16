<script>
  import StatTile from '$lib/components/StatTile.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import { GRAPH_STATS, GRAPH_NODES, GRAPH_COLUMNS } from '$lib/data.js';

  let q = $state('');
  // Client-side filter over the mock nodes (stands in for GET /v1/graph/search).
  let results = $derived(
    q.trim() === ''
      ? GRAPH_NODES
      : GRAPH_NODES.filter((n) => (n.label + ' ' + n.id + ' ' + n.kind).toLowerCase().includes(q.trim().toLowerCase()))
  );
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">Investigate</span><span class="sep">/</span><span class="slug">graph</span></div>
      <h1>Graph</h1>
    </div>
    <input class="search" type="search" bind:value={q} placeholder="Search nodes · actor, persona, source…" spellcheck="false" />
  </div>

  <div class="body">
    <div class="tiles">
      {#each GRAPH_STATS as s}
        <StatTile {...s} />
      {/each}
    </div>

    <Panel title="Node search" class="grow">
      {#snippet action()}<span class="count">{results.length} / {GRAPH_NODES.length}</span>{/snippet}
      {#if results.length}
        <DataTable rowKey="id" columns={GRAPH_COLUMNS} rows={results} />
      {:else}
        <div class="empty">No nodes match <code>{q}</code>.</div>
      {/if}
    </Panel>

    <p class="note">Topology view (node-link canvas) needs a graph-traversal endpoint that
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
  .note { margin: 12px 0 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }
  code { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-body); background: var(--surface); padding: 1px 5px; border-radius: var(--radius-sm); }
</style>
