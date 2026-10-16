<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { listGraphs, createGraph, deleteGraph, clearGraph } from '$lib/explorer.svelte.js';

  // The Graph Explorer landing page: pick a saved graph to open its map, or start
  // a new one. The map itself lives at /graph/[id].
  let graphs = $state([]);
  let loading = $state(true);
  let error = $state('');

  async function refresh() {
    loading = true; error = '';
    try { graphs = await listGraphs(); }
    catch (e) { error = e.message ?? String(e); }
    finally { loading = false; }
  }
  onMount(refresh);

  async function newGraph() {
    const name = window.prompt('New graph name', 'investigation');
    if (!name) return;
    try { clearGraph(); goto(`/graph/${await createGraph(name)}`); }
    catch (e) { error = e.message ?? String(e); }
  }
  function open(id) { clearGraph(); goto(`/graph/${id}`); }
  async function remove(id, ev) {
    ev.stopPropagation();
    try { await deleteGraph(id); await refresh(); }
    catch (e) { error = e.message ?? String(e); }
  }

  const fmtDate = (s) => (s ? new Date(s).toLocaleString('en-US') : '');
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">Investigate</span><span class="sep">/</span><span class="slug">explorer</span></div>
      <h1>Graph Explorer</h1>
    </div>
    <button class="new" onclick={newGraph}>+ New graph</button>
  </div>

  <div class="body">
    {#if error}<p class="note">{error}</p>{/if}
    {#if loading}
      <p class="empty">Loading saved graphs…</p>
    {:else if !graphs.length}
      <p class="empty">No saved graphs yet. Start one with <b>+ New graph</b>.</p>
    {:else}
      <div class="grid">
        {#each graphs as g (g.id)}
          <div class="card" role="button" tabindex="0"
            onclick={() => open(g.id)}
            onkeydown={(e) => { if (e.key === 'Enter') open(g.id); }}>
            <div class="c-top">
              <span class="c-name">{g.name}</span>
              <button class="c-del" onclick={(e) => remove(g.id, e)} aria-label="delete">×</button>
            </div>
            {#if g.description}<div class="c-desc">{g.description}</div>{/if}
            <div class="c-meta">updated {fmtDate(g.updated_at)}</div>
          </div>
        {/each}
      </div>
    {/if}
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
  .new { height: 32px; padding: 0 14px; background: var(--accent-fill, var(--surface)); border: 1px solid var(--accent); border-radius: var(--radius); color: var(--accent-text); font-family: var(--font-mono); font-size: var(--fs-12); cursor: pointer; }
  .new:hover { background: var(--accent); color: var(--black); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 20px; }
  .empty { padding: 20px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }
  .empty b { color: var(--text-body); }
  .note { margin: 0 0 16px; padding: 12px; border: 1px solid var(--red-text, #e07b76); border-radius: var(--radius); font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text, #e07b76); }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
  .card { padding: 14px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); cursor: pointer; transition: border-color .12s; }
  .card:hover { border-color: var(--accent); }
  .c-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .c-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-sans); font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text); }
  .c-del { background: none; border: 0; color: var(--text-faint); font-size: 16px; line-height: 1; cursor: pointer; }
  .c-del:hover { color: var(--red-text, #e07b76); }
  .c-desc { margin-top: 6px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .c-meta { margin-top: 10px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
</style>
