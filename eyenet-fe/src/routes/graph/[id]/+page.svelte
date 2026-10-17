<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import GraphCanvas from '$lib/components/GraphCanvas.svelte';
  import GraphPalette from '$lib/components/GraphPalette.svelte';
  import Graph from 'phosphor-svelte/lib/Graph';
  import TreeStructure from 'phosphor-svelte/lib/TreeStructure';
  import Target from 'phosphor-svelte/lib/Target';
  import SquaresFour from 'phosphor-svelte/lib/SquaresFour';
  import CornersOut from 'phosphor-svelte/lib/CornersOut';
  import MagnifyingGlassPlus from 'phosphor-svelte/lib/MagnifyingGlassPlus';
  import MagnifyingGlassMinus from 'phosphor-svelte/lib/MagnifyingGlassMinus';
  import Snowflake from 'phosphor-svelte/lib/Snowflake';
  import Sparkle from 'phosphor-svelte/lib/Sparkle';
  import { ui } from '$lib/ui.svelte.js';
  import {
    explorer, seedSearch, addSeed, fetchCounts, expandNode, clearGraph,
    EDGE_KINDS, assertEdge, loadNote, saveNote,
    GROUP_KINDS, createOperatorEntity,
    saveGraph, loadGraph, searchEntities, removeNodes, deleteEdge, classifyEdgeDeletion
  } from '$lib/explorer.svelte.js';

  // Canvas api handle (positions + view controls).
  let canvasApi = null;

  // ── View toolbar state.
  let frozen = $state(false);
  let animOn = $state(true);
  let activeLayout = $state('fcose');
  const LAYOUTS = [
    { id: 'fcose', icon: Graph, title: 'Force layout' },
    { id: 'dagre', icon: TreeStructure, title: 'Tree layout' },
    { id: 'concentric', icon: Target, title: 'Concentric layout' },
    { id: 'grid', icon: SquaresFour, title: 'Grid layout' }
  ];
  function fitView() { canvasApi?.fit?.(); }
  function setLayout(id) { activeLayout = id; canvasApi?.setLayout?.(id); }
  function zoomIn() { canvasApi?.zoom?.(1.2); }
  function zoomOut() { canvasApi?.zoom?.(1 / 1.2); }
  function toggleFreeze() { frozen = !frozen; canvasApi?.setFrozen?.(frozen); }
  function toggleAnim() { animOn = !animOn; canvasApi?.setAnimations?.(animOn); }

  // Load the graph named in the route (and reload if the route id changes).
  $effect(() => {
    const id = $page.params.id;
    if (id) loadGraph(id);
  });

  async function doSave() {
    try { await saveGraph(explorer.graphName || 'untitled', canvasApi?.positions?.() ?? []); }
    catch { /* explorer.error */ }
  }

  // Auto-hide the global nav rail while in the map (fullscreen workspace); restore on leave.
  onMount(() => {
    const prior = ui.navCollapsed;
    ui.navCollapsed = true;
    return () => { ui.navCollapsed = prior; };
  });

  // Palette drag -> drop on canvas -> quick-add popover at the drop point: type a
  // name, arrow-pick an existing match, Enter to add it (or create a new one).
  const DRAG_MIME = 'application/x-eyenet-entity';
  const TYPE_WORD = (s) => (s.kind === 'artifact' ? s.artifactKind : s.kind);
  function dropScope(spec) {
    return spec.kind === 'artifact'
      ? { dsl: `artifact.kind:${spec.artifactKind}` }
      : { types: spec.kind };
  }
  let quickAdd = $state(null); // { x, y, spec, q, results, sel } | null
  let qaTimer;
  function onCanvasDrop(e) {
    e.preventDefault();
    const raw = e.dataTransfer?.getData(DRAG_MIME);
    if (!raw) return;
    let spec;
    try { spec = JSON.parse(raw); } catch { return; }
    const rect = e.currentTarget.getBoundingClientRect();
    // Centered on the cursor (translate -50%), but clamped inside the stage so it never
    // spills over the palette on the left or off the edges.
    const halfW = 124;
    const x = Math.max(halfW, Math.min(e.clientX - rect.left, rect.width - halfW));
    const y = Math.max(90, Math.min(e.clientY - rect.top, rect.height - 90));
    menu = null; selNode = null;
    quickAdd = { x, y, spec, q: '', results: [], sel: 0 };
  }
  function qaInput() {
    clearTimeout(qaTimer);
    const qa = quickAdd;
    qaTimer = setTimeout(async () => {
      if (!quickAdd || quickAdd !== qa) return;
      const results = await searchEntities(dropScope(qa.spec), qa.q);
      if (quickAdd === qa) quickAdd = { ...quickAdd, results, sel: 0 };
    }, 180);
  }
  async function qaCreate(q) {
    const s = quickAdd.spec;
    quickAdd = null;
    const payload =
      s.kind === 'actor' ? { handle: q.trim() || null, display_name: null }
      : s.kind === 'group' ? { title: q.trim(), kind: 'chat' }
      : s.kind === 'crew' ? { name: q.trim(), members: [] }
      : s.kind === 'persona' ? { label: q.trim() }
      : { kind: s.artifactKind, value: q.trim() };
    try { await createOperatorEntity(s.kind, payload); } catch { /* explorer.error */ }
  }
  function focusEl(node) { node.focus(); }
  function qaKey(e) {
    if (!quickAdd) return;
    const n = quickAdd.results.length; // index n == the "create new" row
    if (e.key === 'ArrowDown') { e.preventDefault(); quickAdd = { ...quickAdd, sel: Math.min(quickAdd.sel + 1, n) }; }
    else if (e.key === 'ArrowUp') { e.preventDefault(); quickAdd = { ...quickAdd, sel: Math.max(quickAdd.sel - 1, 0) }; }
    else if (e.key === 'Escape') { quickAdd = null; }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (quickAdd.sel < n) { addSeed(quickAdd.results[quickAdd.sel]); quickAdd = null; }
      else if (quickAdd.q.trim()) qaCreate(quickAdd.q);
    }
  }

  // ── Left-click a node → inspector flyout (the raw mapped node).
  let selNode = $state(null);

  // ── Right-click a node → enrichment menu with degree counts.
  //    { x, y, node, loading, items: [[name, count]] } | null
  let menu = $state(null);
  async function onNodeContext(node, pos) {
    selNode = null;
    // If the right-clicked node is part of a multi-selection, the menu acts on the whole
    // selection; otherwise just this node.
    const sel = canvasApi?.selectedIds?.() ?? [];
    const selCount = sel.includes(node.id) && sel.length > 1 ? sel.length : 0;
    menu = { x: pos.x, y: pos.y, node, loading: true, items: [], selCount };
    try {
      const counts = await fetchCounts(node);
      // keep menu only if still the same node (no newer right-click)
      if (menu && menu.node === node) menu = { ...menu, loading: false, items: Object.entries(counts) };
    } catch (e) {
      if (menu && menu.node === node) menu = { ...menu, loading: false, error: e.message ?? String(e) };
    }
  }
  // Enriching a hub (e.g. the t.me domain, shared by every Telegram link) can dump
  // thousands of nodes and wedge the canvas. Warn past this count before expanding.
  const BIG_ENRICH = 250;
  function guardedExpand(node, name, count) {
    if (count != null && count > BIG_ENRICH &&
        !confirm(`"${name}" adds ${Number(count).toLocaleString('en-US')} nodes and may bog the canvas. Continue?`)) return;
    expandNode(node, name);
  }
  function runEnrichment(name) {
    const node = menu?.node;
    const count = menu?.items?.find(([n]) => n === name)?.[1] ?? null;
    menu = null;
    if (node) guardedExpand(node, name, count);
  }
  // Remove from the graph VIEW (cascading orphan-sweep; never touches the DB). Acts on the
  // multi-selection if the node is part of one, else just the node.
  function removeFromGraph(node) {
    const sel = canvasApi?.selectedIds?.() ?? [];
    const ids = sel.includes(node.id) && sel.length > 1 ? sel : [node.id];
    removeNodes(ids);
    canvasApi?.clearSelection?.();
    menu = null;
    selNode = null;
  }
  // Delete / Backspace removes the current selection (or the inspected node), unless the
  // operator is typing in a field.
  function onKeydown(e) {
    if (e.key !== 'Delete' && e.key !== 'Backspace') return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    const sel = canvasApi?.selectedIds?.() ?? [];
    if (sel.length) { e.preventDefault(); removeNodes(sel); canvasApi?.clearSelection?.(); selNode = null; }
    else if (selNode) { e.preventDefault(); removeNodes([selNode.id]); selNode = null; }
  }

  // Right-click ANY edge → a menu to delete it. The label/behaviour depends on what the
  // edge means (unlink persona, remove from crew, retract asserted, or just prune).
  let edgeMenu = $state(null); // { x, y, edge, s, d, label } | null
  function onEdgeContext(edge, pos) {
    menu = null; selNode = null;
    const byId = Object.fromEntries(explorer.nodes.map((n) => [n.id, n]));
    const s = byId[edge.srcId];
    const d = byId[edge.dstId];
    const { label } = classifyEdgeDeletion(edge, s, d);
    edgeMenu = { x: pos.x, y: pos.y, edge, s, d, label };
  }
  function doDeleteEdge() {
    if (!edgeMenu) return;
    const { edge, s, d } = edgeMenu;
    edgeMenu = null;
    deleteEdge(edge, s, d);
  }

  // Double-click a node → run its type's default enrichment (the mockup's one-shot expand).
  const DEFAULT_ENRICH = {
    actor: 'messages',
    artifact: 'messages',
    message: 'author',
    thread: 'messages',
    group: 'messages',
    document: 'artifacts',
    persona: 'actors'
  };
  async function onNodeDblClick(node) {
    menu = null;
    const name = DEFAULT_ENRICH[node.entityType];
    if (!name) return;
    // No count in hand on a dblclick; fetch it so the same big-expand guard applies.
    let count = null;
    try { count = (await fetchCounts(node))[name] ?? null; } catch { /* guard best-effort */ }
    guardedExpand(node, name, count);
  }

  const fieldRows = $derived(selNode ? Object.entries(selNode.fields ?? {}) : []);
  const fmtCount = (c) => (c == null ? '·' : Number(c).toLocaleString('en-US'));
  const edgeLabel = (k) => k.replace(/_/g, ' ');

  // ── Shift-drag between two nodes → edge-kind picker → assert.
  let edgePicker = $state(null); // { src, dst, custom, reason } | null
  function onConnectReady(src, dst) {
    edgePicker = { src, dst, custom: '', reason: 'linked in explorer' };
  }
  async function doAssert(kind) {
    const k = (kind ?? edgePicker.custom).trim();
    if (!k || !edgePicker) return;
    const { src, dst, reason } = edgePicker;
    edgePicker = null;
    try { await assertEdge(src, dst, k, reason); } catch { /* surfaced via explorer.error */ }
  }

  // ── Inspector notes: load on selection, save on demand.
  let noteBody = $state('');
  let noteSaving = $state(false);
  let noteStatus = $state('');
  let noteSeq = 0;
  $effect(() => {
    const n = selNode;
    noteStatus = '';
    if (!n) { noteBody = ''; return; }
    const mine = ++noteSeq;
    loadNote(n).then((b) => { if (mine === noteSeq) noteBody = b; }).catch(() => {});
  });
  async function doSaveNote() {
    if (!selNode) return;
    noteSaving = true; noteStatus = '';
    try { await saveNote(selNode, noteBody); noteStatus = 'saved'; }
    catch (e) { noteStatus = e.message ?? 'error'; }
    finally { noteSaving = false; }
  }

  // ── Operator-entity creation modal.
  let newEnt = $state(null); // { type, handle, display_name, title, kind, akind, value } | null
  function openNew(type = 'artifact', artifactKind = '') {
    menu = null;
    newEnt = { type, handle: '', display_name: '', title: '', kind: 'chat', akind: artifactKind, value: '' };
  }
  const newValid = $derived(
    !newEnt ? false
    : newEnt.type === 'actor' ? !!(newEnt.handle.trim() || newEnt.display_name.trim())
    : newEnt.type === 'group' ? !!newEnt.title.trim()
    : /^[a-z][a-z0-9_]{1,63}$/.test(newEnt.akind.trim()) && !!newEnt.value.trim()
  );
  async function doCreate() {
    if (!newEnt || !newValid) return;
    const e = newEnt;
    const payload =
      e.type === 'actor' ? { handle: e.handle.trim() || null, display_name: e.display_name.trim() || null }
      : e.type === 'group' ? { title: e.title.trim(), kind: e.kind }
      : { kind: e.akind.trim(), value: e.value.trim() };
    newEnt = null;
    try { await createOperatorEntity(e.type, payload); } catch { /* surfaced via explorer.error */ }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<main>
  <div class="head">
    <div>
      <div class="crumb"><button class="back" onclick={() => goto('/graph')}>← Graphs</button><span class="sep">/</span><span class="slug">{explorer.graphName || 'map'}</span></div>
      <h1>Graph Explorer</h1>
    </div>
    <div class="tools">
      <button class="btn" onclick={doSave} disabled={!explorer.nodes.length}>Save</button>
      <button class="btn" onclick={() => openNew()}>+ New</button>
      <button class="btn" onclick={clearGraph} disabled={!explorer.nodes.length}>Clear</button>
    </div>
  </div>

  <div class="work">
    <GraphPalette />
    <div class="stage" role="presentation" ondragover={(e) => e.preventDefault()} ondrop={onCanvasDrop}>
      {#if !explorer.nodes.length}
        <div class="hint">Search the <b>palette</b> to seed a node, then <b>right-click</b> it to
          enrich. Drag a type from the palette onto the canvas to create one.</div>
      {/if}

      <GraphCanvas
      nodes={explorer.nodes}
      edges={explorer.edges}
      onNodeClick={(n) => { selNode = n; menu = null; }}
      {onNodeDblClick}
      onNodeContext={onNodeContext}
      onEdgeContext={onEdgeContext}
      onConnectReady={onConnectReady}
      onCanvasTap={() => { menu = null; edgeMenu = null; selNode = null; quickAdd = null; }}
      onReady={(api) => (canvasApi = api)}
    />

    {#if quickAdd}
      <div class="qa" style="left:{quickAdd.x}px; top:{quickAdd.y}px">
        <input class="qa-input" bind:value={quickAdd.q} oninput={qaInput} onkeydown={qaKey}
          use:focusEl placeholder="{TYPE_WORD(quickAdd.spec)} name…" spellcheck="false" />
        <div class="qa-list">
          {#each quickAdd.results as r, i (r.entity_id)}
            <button class="qa-row" class:sel={quickAdd.sel === i}
              onmouseenter={() => (quickAdd = { ...quickAdd, sel: i })}
              onclick={() => { addSeed(r); quickAdd = null; }}>
              <span class="dot" style="background:var(--etype-{r.entity_type}, var(--etype-default))"></span>
              <span class="qa-t">{r.title || r.entity_id}</span>
            </button>
          {/each}
          <button class="qa-row qa-new" class:sel={quickAdd.sel === quickAdd.results.length}
            onmouseenter={() => (quickAdd = { ...quickAdd, sel: quickAdd.results.length })}
            onclick={() => quickAdd.q.trim() && qaCreate(quickAdd.q)}>
            + Create {TYPE_WORD(quickAdd.spec)}{quickAdd.q.trim() ? ` “${quickAdd.q.trim()}”` : ''}
          </button>
        </div>
      </div>
    {/if}

    <!-- view toolbar -->
    <div class="viewbar">
      {#each LAYOUTS as l}
        {@const Icon = l.icon}
        <button class="vb" class:on={activeLayout === l.id} onclick={() => setLayout(l.id)} title={l.title}><Icon size={18} weight="bold" /></button>
      {/each}
      <div class="vb-div"></div>
      <button class="vb" onclick={fitView} title="Fit to view"><CornersOut size={18} weight="bold" /></button>
      <button class="vb" onclick={zoomIn} title="Zoom in"><MagnifyingGlassPlus size={18} weight="bold" /></button>
      <button class="vb" onclick={zoomOut} title="Zoom out"><MagnifyingGlassMinus size={18} weight="bold" /></button>
      <button class="vb" class:on={frozen} onclick={toggleFreeze} title={frozen ? 'Frozen (click to unlock)' : 'Freeze node positions'}><Snowflake size={18} weight={frozen ? 'fill' : 'bold'} /></button>
      <button class="vb" class:on={animOn} onclick={toggleAnim} title={animOn ? 'Spring animation on' : 'Spring animation off'}><Sparkle size={18} weight={animOn ? 'fill' : 'bold'} /></button>
    </div>

    {#if explorer.busy}<div class="busy">Enriching…</div>{/if}
    {#if explorer.error}<div class="err">{explorer.error}</div>{/if}

    <!-- right-click enrichment menu -->
    {#if menu}
      <div class="ctxmenu" style="left:{menu.x}px; top:{menu.y}px">
        <div class="ctx-head">{menu.node.entityType} · enrich</div>
        {#if menu.loading}
          <div class="ctx-empty">Counting…</div>
        {:else if menu.error}
          <div class="ctx-empty">No enrichments available</div>
        {:else if menu.items.length}
          {#each menu.items as [name, count]}
            <button class="ctx-row" onclick={() => runEnrichment(name)}>
              <span>{name}</span><span class="ctx-count">{fmtCount(count)}</span>
            </button>
          {/each}
        {:else}
          <div class="ctx-empty">No enrichments</div>
        {/if}
        <div class="ctx-div"></div>
        <button class="ctx-row danger" onclick={() => removeFromGraph(menu.node)}>
          {menu.selCount ? `Remove ${menu.selCount} selected` : 'Remove from graph'}
        </button>
      </div>
    {/if}

    <!-- right-click any edge → delete it (semantics depend on edge type) -->
    {#if edgeMenu}
      <div class="ctxmenu" style="left:{edgeMenu.x}px; top:{edgeMenu.y}px">
        <div class="ctx-head">{edgeMenu.edge.kind?.replace(/_/g, ' ') || 'edge'}</div>
        <button class="ctx-row danger" onclick={doDeleteEdge}>{edgeMenu.label}</button>
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

        <div class="ins-notes">
          <div class="ins-label">Notes</div>
          <textarea class="note" bind:value={noteBody} placeholder="Operator note for this entity…" rows="5"></textarea>
          <div class="note-bar">
            <button class="btn" onclick={doSaveNote} disabled={noteSaving}>{noteSaving ? 'Saving…' : 'Save'}</button>
            {#if noteStatus}<span class="note-status">{noteStatus}</span>{/if}
          </div>
        </div>
      </aside>
    {/if}

    <!-- edge-kind picker (shift-drag between two nodes) -->
    {#if edgePicker}
      <div class="edge-pick-scrim" role="presentation" onclick={() => (edgePicker = null)}></div>
      <div class="edge-pick">
        <div class="ep-head">Link <b>{edgePicker.src.title || edgePicker.src.entityType}</b> → <b>{edgePicker.dst.title || edgePicker.dst.entityType}</b></div>
        <div class="ep-kinds">
          {#each EDGE_KINDS as k}
            <button class="ep-kind" onclick={() => doAssert(k)}>{edgeLabel(k)}</button>
          {/each}
        </div>
        <div class="ep-custom">
          <input class="search" bind:value={edgePicker.custom} placeholder="custom kind…" spellcheck="false"
            onkeydown={(e) => { if (e.key === 'Enter') doAssert(); }} />
          <button class="btn" onclick={() => doAssert()} disabled={!edgePicker.custom.trim()}>Add</button>
        </div>
        <input class="search ep-reason" bind:value={edgePicker.reason} placeholder="reason" spellcheck="false" />
      </div>
    {/if}

    <!-- operator-entity creation -->
    {#if newEnt}
      <div class="edge-pick-scrim" role="presentation" onclick={() => (newEnt = null)}></div>
      <div class="edge-pick nm">
        <div class="ep-head">New operator entity</div>
        <div class="ep-kinds">
          {#each ['actor', 'group', 'artifact'] as t}
            <button class="ep-kind" class:on={newEnt.type === t} onclick={() => (newEnt.type = t)}>{t}</button>
          {/each}
        </div>
        {#if newEnt.type === 'actor'}
          <input class="search ep-reason" bind:value={newEnt.handle} placeholder="handle" spellcheck="false" />
          <input class="search ep-reason" bind:value={newEnt.display_name} placeholder="display name" spellcheck="false" />
        {:else if newEnt.type === 'group'}
          <input class="search ep-reason" bind:value={newEnt.title} placeholder="title" spellcheck="false" />
          <select class="search ep-reason" bind:value={newEnt.kind}>
            {#each GROUP_KINDS as k}<option value={k}>{k}</option>{/each}
          </select>
        {:else}
          <input class="search ep-reason" bind:value={newEnt.akind} placeholder="kind (e.g. wallet_btc, onion, domain)" spellcheck="false" />
          <input class="search ep-reason" bind:value={newEnt.value} placeholder="value" spellcheck="false" />
        {/if}
        <div class="note-bar">
          <button class="btn" onclick={doCreate} disabled={!newValid}>Create</button>
          <button class="btn" onclick={() => (newEnt = null)}>Cancel</button>
        </div>
      </div>
    {/if}
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { flex: 0 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .sep { color: var(--text-faint); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }

  .tools { display: flex; align-items: center; gap: 10px; }
  .work { flex: 1; min-height: 0; display: flex; }
  .search { width: 340px; max-width: 42vw; height: 30px; padding: 0 10px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  .search::placeholder { color: var(--text-faint); }
  .search:focus { outline: none; border-color: var(--accent); }
  .btn { height: 30px; padding: 0 12px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-11); cursor: pointer; }
  .btn:disabled { opacity: 0.45; cursor: default; }
  .back { background: none; border: 0; padding: 0; color: var(--text-faint); font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); cursor: pointer; }
  .back:hover { color: var(--accent-text); }

  .ctx-empty { padding: 10px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  .dot { flex: 0 0 auto; width: 8px; height: 8px; border-radius: 50%; }

  /* drop-to-add quick popover */
  .qa { position: absolute; z-index: 32; width: 240px; transform: translate(-50%, -50%); background: var(--panel-2, var(--surface)); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0,0,0,.5); overflow: hidden; }
  .qa-input { width: 100%; height: 30px; padding: 0 10px; background: var(--surface); border: 0; border-bottom: 1px solid var(--border); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); }
  .qa-input:focus { outline: none; }
  .qa-list { max-height: 260px; overflow-y: auto; }
  .qa-row { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 10px; background: none; border: 0; cursor: pointer; text-align: left; }
  .qa-row.sel { background: var(--surface); }
  .qa-t { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-body); }
  .qa-new { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); border-top: 1px solid var(--border); }

  .stage { position: relative; flex: 1; min-width: 0; min-height: 0; }
  .viewbar { position: absolute; top: 12px; left: 12px; z-index: 7; display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 0; background: none; border: 0; }
  .vb-div { width: 18px; height: 1px; margin: 4px 0; background: var(--border-strong); }
  .vb { display: grid; place-items: center; width: 30px; height: 30px; padding: 0; background: none; border: 1px solid transparent; border-radius: 7px; color: var(--text-muted); cursor: pointer; transition: color .1s, background .1s, border-color .1s; }
  .vb:hover { color: var(--accent-text); background: color-mix(in srgb, var(--accent) 10%, transparent); }
  .vb.on { background: color-mix(in srgb, var(--accent) 16%, transparent); border-color: color-mix(in srgb, var(--accent) 55%, transparent); color: var(--accent); }
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
  .ctx-div { height: 1px; margin: 2px 0; background: var(--border); }
  .ctx-row.danger { color: var(--danger, #f87171); }
  .ctx-row.danger:hover { background: color-mix(in srgb, var(--danger, #f87171) 16%, transparent); color: var(--danger, #f87171); }

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

  .ins-notes { margin-top: 16px; }
  .ins-label { margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .note { width: 100%; resize: vertical; padding: 8px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); line-height: var(--lh-normal); }
  .note:focus { outline: none; border-color: var(--accent); }
  .note-bar { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
  .note-status { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }

  .edge-pick-scrim { position: absolute; inset: 0; z-index: 40; background: rgba(0,0,0,.35); }
  .edge-pick { position: absolute; z-index: 41; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 320px; padding: 14px; background: var(--panel-2, var(--surface)); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 10px 30px rgba(0,0,0,.55); }
  .ep-head { margin-bottom: 10px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  .ep-head b { color: var(--text-body); }
  .ep-kinds { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .ep-kind { padding: 5px 9px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-11); cursor: pointer; }
  .ep-kind:hover { border-color: var(--accent); color: var(--accent-text); }
  .ep-custom { display: flex; gap: 6px; margin-bottom: 8px; }
  .ep-custom .search { flex: 1; width: auto; max-width: none; }
  .ep-reason { display: block; width: 100%; max-width: none; margin-bottom: 8px; }
  .ep-kind.on { border-color: var(--accent); color: var(--accent-text); }
  .nm select.search { height: 30px; }
</style>
