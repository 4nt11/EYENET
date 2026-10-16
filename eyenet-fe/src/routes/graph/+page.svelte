<script>
  import GraphCanvas from '$lib/components/GraphCanvas.svelte';
  import { explorer, seedSearch, addSeed, fetchCounts, expandNode, clearGraph } from '$lib/explorer.svelte.js';

  // ── Seed search (top bar): debounced global search; a result drops onto canvas.
  let q = $state('');
  let seedOpen = $state(false);
  let timer;
  $effect(() => {
    const term = q;
    clearTimeout(timer);
    timer = setTimeout(() => seedSearch(term), 200);
    return () => clearTimeout(timer);
  });

  function dropSeed(hit) {
    addSeed(hit);
    q = '';
    seedOpen = false;
    explorer.seedResults = [];
  }

  // ── Left-click a node → inspector flyout (the raw mapped node).
  let selNode = $state(null);

  // ── Right-click a node → enrichment menu with degree counts.
  //    { x, y, node, loading, items: [[name, count]] } | null
  let menu = $state(null);
  async function onNodeContext(node, pos) {
    selNode = null;
    menu = { x: pos.x, y: pos.y, node, loading: true, items: [] };
    try {
      const counts = await fetchCounts(node);
      // keep menu only if still the same node (no newer right-click)
      if (menu && menu.node === node) menu = { ...menu, loading: false, items: Object.entries(counts) };
    } catch (e) {
      if (menu && menu.node === node) menu = { ...menu, loading: false, error: e.message ?? String(e) };
    }
  }
  function runEnrichment(name) {
    const node = menu?.node;
    menu = null;
    if (node) expandNode(node, name);
  }

  const fieldRows = $derived(selNode ? Object.entries(selNode.fields ?? {}) : []);
  const fmtCount = (c) => (c == null ? '·' : Number(c).toLocaleString('en-US'));
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">Investigate</span><span class="sep">/</span><span class="slug">explorer</span></div>
      <h1>Graph Explorer</h1>
    </div>
    <div class="tools">
      <div class="seed">
        <input
          class="search" type="search" bind:value={q}
          onfocus={() => (seedOpen = true)}
          placeholder="Search any entity to seed the canvas…" spellcheck="false" />
        {#if seedOpen && (explorer.seedLoading || explorer.seedResults.length)}
          <div class="drop">
            {#if explorer.seedLoading}
              <div class="drop-empty">Searching…</div>
            {:else}
              {#each explorer.seedResults as hit (hit.entity_id)}
                <button class="drop-row" onclick={() => dropSeed(hit)}>
                  <span class="dot" style="background:var(--etype-{hit.entity_type}, var(--etype-default))"></span>
                  <span class="d-title">{hit.title || hit.entity_id}</span>
                  <span class="d-type">{hit.entity_type}</span>
                </button>
              {/each}
            {/if}
          </div>
        {/if}
      </div>
      <button class="btn" onclick={clearGraph} disabled={!explorer.nodes.length}>Clear</button>
    </div>
  </div>

  <div class="stage" role="presentation" onclick={() => (seedOpen = false)}>
    {#if !explorer.nodes.length}
      <div class="hint">Search an actor, wallet, onion, group or message above, then
        <b>right-click</b> a node to enrich it. Double-click + drag to rearrange; shift-drag to link.</div>
    {/if}

    <GraphCanvas
      nodes={explorer.nodes}
      edges={explorer.edges}
      onNodeClick={(n) => { selNode = n; menu = null; }}
      onNodeContext={onNodeContext}
      onCanvasTap={() => { menu = null; }}
    />

    {#if explorer.busy}<div class="busy">Enriching…</div>{/if}
    {#if explorer.error}<div class="err">{explorer.error}</div>{/if}

    <!-- right-click enrichment menu -->
    {#if menu}
      <div class="ctxmenu" style="left:{menu.x}px; top:{menu.y}px">
        <div class="ctx-head">{menu.node.entityType} · enrich</div>
        {#if menu.loading}
          <div class="ctx-empty">Counting…</div>
        {:else if menu.error}
          <div class="ctx-empty">{menu.error}</div>
        {:else if menu.items.length}
          {#each menu.items as [name, count]}
            <button class="ctx-row" onclick={() => runEnrichment(name)}>
              <span>{name}</span><span class="ctx-count">{fmtCount(count)}</span>
            </button>
          {/each}
        {:else}
          <div class="ctx-empty">No enrichments</div>
        {/if}
      </div>
    {/if}

    <!-- inspector flyout -->
    {#if selNode}
      <aside class="inspector">
        <div class="ins-head">
          <span class="dot" style="background:var(--etype-{selNode.entityType}, var(--etype-default))"></span>
          <span class="ins-type">{selNode.entityType}</span>
          <button class="x" onclick={() => (selNode = null)} aria-label="close">×</button>
        </div>
        <div class="ins-title">{selNode.title || selNode.id}</div>
        <div class="ins-id">{selNode.id}</div>
        {#if fieldRows.length}
          <table class="ins-fields">
            <tbody>
              {#each fieldRows as [k, v]}
                <tr><th>{k}</th><td>{typeof v === 'object' ? JSON.stringify(v) : v}</td></tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </aside>
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

  .tools { display: flex; align-items: center; gap: 10px; }
  .seed { position: relative; }
  .search { width: 340px; max-width: 42vw; height: 30px; padding: 0 10px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  .search::placeholder { color: var(--text-faint); }
  .search:focus { outline: none; border-color: var(--accent); }
  .btn { height: 30px; padding: 0 12px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-11); cursor: pointer; }
  .btn:disabled { opacity: 0.45; cursor: default; }

  .drop { position: absolute; top: 34px; right: 0; width: 100%; max-height: 320px; overflow-y: auto; z-index: 20; background: var(--panel-2, var(--surface)); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0,0,0,.5); }
  .drop-row { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 10px; background: none; border: 0; border-bottom: 1px solid var(--border); cursor: pointer; text-align: left; }
  .drop-row:hover { background: var(--surface); }
  .d-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-body); }
  .d-type { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .drop-empty, .ctx-empty { padding: 10px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  .dot { flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%; }

  .stage { position: relative; flex: 1; min-height: 0; }
  .hint { position: absolute; top: 16px; left: 50%; transform: translateX(-50%); z-index: 5; max-width: 560px; padding: 10px 14px; text-align: center; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  .hint b { color: var(--text-body); }
  .busy, .err { position: absolute; bottom: 14px; left: 14px; z-index: 6; padding: 6px 10px; border-radius: var(--radius); font-family: var(--font-mono); font-size: var(--fs-11); }
  .busy { background: var(--surface); border: 1px solid var(--border-strong); color: var(--text-muted); }
  .err { background: var(--red-fill, #3a1a1a); border: 1px solid var(--red-text, #e07b76); color: var(--red-text, #e07b76); }

  .ctxmenu { position: absolute; z-index: 30; min-width: 200px; background: var(--panel-2, var(--surface)); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0,0,0,.5); overflow: hidden; }
  .ctx-head { padding: 6px 10px; border-bottom: 1px solid var(--border); font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .ctx-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; padding: 7px 10px; background: none; border: 0; cursor: pointer; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); }
  .ctx-row:hover { background: var(--surface); color: var(--accent-text); }
  .ctx-count { color: var(--text-faint); }

  .inspector { position: absolute; top: 0; right: 0; bottom: 0; width: 320px; z-index: 15; overflow-y: auto; padding: 14px; background: var(--panel-2, var(--surface)); border-left: 1px solid var(--border-strong); }
  .ins-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
  .ins-type { flex: 1; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .x { background: none; border: 0; color: var(--text-faint); font-size: 18px; line-height: 1; cursor: pointer; }
  .x:hover { color: var(--text-body); }
  .ins-title { font-family: var(--font-sans); font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text); word-break: break-word; }
  .ins-id { margin: 2px 0 12px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); word-break: break-all; }
  .ins-fields { width: 100%; border-collapse: collapse; }
  .ins-fields th { width: 38%; padding: 4px 8px 4px 0; text-align: left; vertical-align: top; font-family: var(--font-mono); font-size: var(--fs-11); font-weight: var(--fw-normal); color: var(--text-faint); }
  .ins-fields td { padding: 4px 0; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-body); word-break: break-word; }
  .ins-fields tr { border-bottom: 1px solid var(--border); }
</style>
