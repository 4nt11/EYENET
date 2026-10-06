<script>
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Button from '$lib/components/Button.svelte';
  import Segmented from '$lib/components/Segmented.svelte';
  import ColumnPicker from '$lib/components/ColumnPicker.svelte';
  import EntityDetail from '$lib/components/EntityDetail.svelte';
  import GraphCanvas from '$lib/components/GraphCanvas.svelte';
  import EdgeModal from '$lib/components/EdgeModal.svelte';
  import {
    searchCtx, runSearch, loadMoreSearch, setTypeFilter, setSourceFilter,
    sourceName, fieldKeyUnion, fieldValue
  } from '$lib/search.svelte.js';
  import {
    graphCtx, runGraph, assertEdge, retractEdge, graphSourceName
  } from '$lib/searchGraph.svelte.js';

  const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
  const ETYPES = ['actor', 'persona', 'crew', 'case', 'group', 'thread', 'message', 'mention', 'incident', 'document', 'attachment', 'artifact'];

  // ── View toggle (Table | Graph), persisted per-viewer (localStorage guarded).
  const VIEW_KEY = 'eyenet_search_view';
  const COLS_KEY = 'eyenet_search_columns';
  function loadView() { try { return localStorage.getItem(VIEW_KEY) === 'graph' ? 'graph' : 'table'; } catch { return 'table'; } }
  function saveView(v) { try { localStorage.setItem(VIEW_KEY, v); } catch { /* best-effort */ } }

  const DEFAULT_COLS = ['type', 'title', 'sourceName', 'date', 'status'];
  function loadCols() {
    try {
      const raw = JSON.parse(localStorage.getItem(COLS_KEY) ?? 'null');
      if (Array.isArray(raw) && raw.length) return raw.includes('title') ? raw : ['title', ...raw];
    } catch { /* fall through to default */ }
    return [...DEFAULT_COLS];
  }
  function saveCols() { try { localStorage.setItem(COLS_KEY, JSON.stringify(selectedCols)); } catch { /* best-effort */ } }

  let view = $state(loadView());
  let selectedCols = $state(loadCols());

  // ── In-page query box, kept in sync with ?q= (top-bar + in-page stay coherent).
  let query = $state('');
  let inputEl;

  $effect(() => {
    const q = $page.url.searchParams.get('q') ?? '';
    query = q;
    runSearch(q);
  });

  // Graph is a second lens on the SAME query + facets — fetch it lazily (only when
  // the Graph tab is active) and re-fetch whenever the query or a facet changes.
  $effect(() => {
    const q = searchCtx.q;
    // track facets so a chip toggle refetches the graph too
    void searchCtx.typeFilter; void searchCtx.sourceFilter;
    if (view === 'graph' && q) runGraph(q);
  });

  function onView() { saveView(view); clearSel(); ctxMenu = null; }
  function submitInPage(e) {
    if (e.key !== 'Enter') return;
    goto(`/search?q=${encodeURIComponent(query.trim())}`);
  }
  function insertField(f) {
    const cur = query.trimEnd();
    query = (cur ? cur + ' ' : '') + f + ':';
    inputEl?.focus();
  }

  // ── Facet chips (shared by both views).
  let typeChips = $derived(Object.entries(searchCtx.byType).sort((a, b) => b[1] - a[1]));
  let sourceChips = $derived(Object.entries(searchCtx.bySource).filter(([id]) => id).sort((a, b) => b[1] - a[1]));

  // ── Query-fields palette → insert `field:` and (where it maps to a loaded
  // column) offer a one-click "add as column".
  const QUERY_FIELDS = [
    { group: 'Message', fields: ['message.content', 'message.author'] },
    { group: 'Group', fields: ['group.title', 'group.status'] },
    { group: 'Forum', fields: ['forum.thread.author'] },
    { group: 'Actor', fields: ['actor.handle'] },
    { group: 'Artifact', fields: ['artifact.value'] },
    { group: 'Case', fields: ['case.title'] },
    { group: 'Document', fields: ['document.text'] }
  ];
  let fieldsOpen = $state(true);

  // ── Configurable columns. Union of keys across the loaded hits' `fields` bags
  // feeds the picker; base columns are always offered.
  let fieldUnion = $derived(fieldKeyUnion(searchCtx.items));
  const BASE_OPTS = [
    { v: 'type', l: 'Type' },
    { v: 'title', l: 'Title', fixed: true },
    { v: 'sourceName', l: 'Source' },
    { v: 'date', l: 'Date' },
    { v: 'status', l: 'Status' }
  ];
  let colOptions = $derived([...BASE_OPTS, ...fieldUnion.map((k) => ({ v: 'f:' + k, l: k }))]);

  const TYPE_TONE = { actor: 'high', persona: 'high', crew: 'high', case: 'warn', incident: 'critical', group: 'medium', thread: 'medium', message: 'neutral', mention: 'neutral', document: 'medium', attachment: 'neutral', artifact: 'warn' };
  const BASE_DEF = {
    type: { key: 'type', header: 'Type', badge: true, tone: (_v, r) => TYPE_TONE[r.entityType] ?? 'neutral', width: '120px' },
    title: { key: 'title', header: 'Title' },
    sourceName: { key: 'sourceName', header: 'Source', mono: true, width: '160px' },
    date: { key: 'date', header: 'Date', mono: true, width: '170px' },
    status: { key: 'status', header: 'Status', mono: true, width: '110px' }
  };
  let columns = $derived(
    selectedCols.map((k) => BASE_DEF[k] ?? { key: k, header: k.startsWith('f:') ? k.slice(2) : k, mono: true })
  );

  // Trim an ISO-ish timestamp to "YYYY-MM-DD HH:MM"; pass anything else through.
  function fmtDate(s) {
    if (!s) return '';
    return typeof s === 'string' && s.includes('T') ? s.slice(0, 16).replace('T', ' ') : String(s);
  }

  // Unified ranked rows (server already applied the type/source facets). Every
  // field-union value is spread under `f:<key>` so toggling a column needs no
  // row rebuild.
  let rows = $derived(
    searchCtx.items.map((it) => {
      const row = {
        id: it.id,
        entityType: it.entityType,
        type: cap(it.entityType),
        title: it.title || '—',
        sourceName: sourceName(it.sourceId),
        date: fmtDate(it.date),
        status: it.status,
        _hit: it
      };
      for (const k of fieldUnion) row['f:' + k] = fieldValue(it, k);
      return row;
    })
  );

  function fieldColKey(f) {
    const seg = f.split('.').pop();
    return fieldUnion.includes(seg) ? 'f:' + seg : null;
  }
  function addCol(colKey) {
    if (!selectedCols.includes(colKey)) { selectedCols = [...selectedCols, colKey]; saveCols(); }
  }

  // ── Selection → shared detail flyout. Table rows carry `fields`; graph nodes
  // don't. Keep the two selections separate so switching tabs doesn't cross-wire.
  let selRow = $state(null);  // a search hit (with .fields)
  let selNode = $state(null); // a graph node
  function clearSel() { selRow = null; selNode = null; }

  // ── Right-click facet menu (graph view): opened at the pointer over empty canvas.
  let ctxMenu = $state(null); // { x, y } container-relative px | null
  function openCtxMenu(pos) { ctxMenu = { x: pos.x, y: pos.y }; }
  function pickType(arg) { setTypeFilter(arg); ctxMenu = null; }
  function pickSource(arg) { setSourceFilter(arg); ctxMenu = null; }

  // ── Edge edit modal (graph). Shift+drag on the canvas maps the node pair.
  let modal = $state(null); // { mode:'connect', src, dst } | { mode:'retract', edge }

  function openConnect(src, dst) { graphCtx.mutateError = null; modal = { mode: 'connect', src, dst }; }
  function openRetract(edge) { graphCtx.mutateError = null; modal = { mode: 'retract', edge }; }
  function closeModal() { modal = null; }

  async function confirmModal(a, b) {
    try {
      if (modal.mode === 'retract') await retractEdge(modal.edge.edgeId, a);
      else await assertEdge(modal.src, modal.dst, a, b);
      closeModal();
    } catch {
      // error surfaces via graphCtx.mutateError inside the modal; keep it open
    }
  }
</script>

<main>
  <SectionHeader group="Investigate" slug="search" title="Search">
    <span class="count">
      {#if !searchCtx.q}idle{:else if searchCtx.total != null}{searchCtx.total} match{searchCtx.total === 1 ? '' : 'es'}{:else}{searchCtx.items.length} loaded{/if}
    </span>
  </SectionHeader>

  <div class="body">
    <div class="searchbar">
      <input
        class="qinput"
        type="search"
        bind:this={inputEl}
        bind:value={query}
        onkeydown={submitInPage}
        placeholder="Search everything — actors, personas, cases, groups, messages, documents…"
        aria-label="Search query"
        spellcheck="false"
      />
      <Button variant="primary" size="md" onclick={() => goto(`/search?q=${encodeURIComponent(query.trim())}`)}>Search</Button>
    </div>

    {#if !searchCtx.q}
      <p class="pnote">Enter a query above (or press <kbd>/</kbd> for the top bar) to search across actors, personas, cases, groups, messages, documents and more.</p>
    {:else if !searchCtx.loaded}
      <p class="pnote">Searching…</p>
    {:else if searchCtx.error}
      <p class="pnote">Search failed: {searchCtx.error}</p>
    {:else}
      <!-- Facet chips live inline in Table view; in Graph view they move to the
           canvas right-click menu (less chrome, more graph). -->
      {#if view === 'table'}
        {#if typeChips.length}
          <div class="facets">
            <button class="chip" class:active={!searchCtx.typeFilter} onclick={() => setTypeFilter(searchCtx.typeFilter)}>All types</button>
            {#each typeChips as [t, n]}
              <button class="chip" class:active={searchCtx.typeFilter === t} onclick={() => setTypeFilter(t)}>{cap(t)} <span class="n">{n}</span></button>
            {/each}
          </div>
        {/if}
        {#if sourceChips.length}
          <div class="facets">
            <button class="chip" class:active={!searchCtx.sourceFilter} onclick={() => setSourceFilter(searchCtx.sourceFilter)}>All sources</button>
            {#each sourceChips as [id, n]}
              <button class="chip mono" class:active={searchCtx.sourceFilter === id} title={id} onclick={() => setSourceFilter(id)}>{sourceName(id)} <span class="n">{n}</span></button>
            {/each}
          </div>
        {/if}
      {/if}

      <div class="toolbar">
        <Segmented options={[{ v: 'table', l: 'Table' }, { v: 'graph', l: 'Graph' }]} bind:value={view} onchange={onView} />
        <div class="toolbar-right">
          {#if view === 'table'}
            <ColumnPicker options={colOptions} bind:selected={selectedCols} onchange={saveCols} label="Columns" />
          {:else}
            <span class="ghint"><kbd>Shift</kbd>+drag a node → another to map an edge · right-click for filters</span>
          {/if}
        </div>
      </div>

      <!-- ═══ TABLE VIEW ═══ -->
      {#if view === 'table'}
        <div class="layout">
          <div class="results">
            {#if rows.length}
              <div class="rframe">
                <DataTable
                  rowKey="id"
                  {columns}
                  {rows}
                  selectedId={selRow?.id}
                  onRowClick={(r) => (selRow = r._hit)}
                  stickyHead
                  stickyTop="0"
                  flat
                  fixed
                />
              </div>
              {#if searchCtx.nextCursor}
                <div class="more">
                  <Button variant="ghost" size="sm" disabled={searchCtx.loadingMore} onclick={loadMoreSearch}>
                    {searchCtx.loadingMore ? 'Loading…' : 'Load more'}
                  </Button>
                </div>
              {/if}
            {:else}
              <p class="pnote">No results for “{searchCtx.q}”.</p>
            {/if}
          </div>

          <aside class="rail">
            <Panel title="Query fields">
              {#snippet action()}
                <button class="collapse" onclick={() => (fieldsOpen = !fieldsOpen)} aria-expanded={fieldsOpen} aria-label="Toggle query fields">{fieldsOpen ? '−' : '+'}</button>
              {/snippet}
              {#if fieldsOpen}
                <div class="fields">
                  <p class="fhint">Click a field to insert <code>field:</code> (scoped text). Operators: <code>==</code> exact, <code>!=</code> not, <code>=~</code> like, plus <code>AND</code>/<code>&&</code>, <code>OR</code>/<code>||</code>, <code>NOT</code> and <code>( )</code>. Where a field maps to a loaded column, use <span class="pluschip">+col</span> to add it as a table column.</p>
                  {#each QUERY_FIELDS as fg}
                    <div class="fgroup">
                      <div class="fgroup-label">{fg.group}</div>
                      <div class="fchips">
                        {#each fg.fields as f}
                          {@const ck = fieldColKey(f)}
                          <span class="fchipwrap">
                            <button class="fchip" onclick={() => insertField(f)} title={`Insert ${f}:`}>{f}</button>
                            {#if ck && !selectedCols.includes(ck)}
                              <button class="pluschip" onclick={() => addCol(ck)} title={`Add "${ck.slice(2)}" column`}>+col</button>
                            {/if}
                          </span>
                        {/each}
                      </div>
                    </div>
                  {/each}
                </div>
              {/if}
            </Panel>

            {#if selRow}
              <EntityDetail entity={selRow} fields={selRow.fields} {sourceName} onClose={() => (selRow = null)} />
            {/if}
          </aside>
        </div>

      <!-- ═══ GRAPH VIEW — full-bleed canvas, legend + inspector float inside ═══ -->
      {:else}
        {#if graphCtx.loading && !graphCtx.nodes.length}
          <p class="pnote">Building graph…</p>
        {:else if graphCtx.error}
          <p class="pnote">Graph failed: {graphCtx.error}</p>
        {:else if !graphCtx.nodes.length}
          <p class="pnote">No graph for “{searchCtx.q}”.</p>
        {:else}
          <div class="gwrap">
            <GraphCanvas
              nodes={graphCtx.nodes}
              edges={graphCtx.edges}
              onNodeClick={(n) => (selNode = n)}
              onConnectReady={openConnect}
              onEdgeRetract={openRetract}
              onBackgroundContext={openCtxMenu}
              onCanvasTap={() => (ctxMenu = null)}
            />

            <!-- right-click facet menu (replaces the inline chip rows in graph view) -->
            {#if ctxMenu}
              <div class="ctxmenu" style="left:{ctxMenu.x}px; top:{ctxMenu.y}px">
                {#if typeChips.length}
                  <div class="ctxsec">
                    <div class="ctxlabel">Type</div>
                    <button class="ctxitem" class:active={!searchCtx.typeFilter} onclick={() => pickType(searchCtx.typeFilter)}>All types</button>
                    {#each typeChips as [t, n]}
                      <button class="ctxitem" class:active={searchCtx.typeFilter === t} onclick={() => pickType(t)}>{cap(t)} <span class="n">{n}</span></button>
                    {/each}
                  </div>
                {/if}
                {#if sourceChips.length}
                  <div class="ctxsec">
                    <div class="ctxlabel">Source</div>
                    <button class="ctxitem" class:active={!searchCtx.sourceFilter} onclick={() => pickSource(searchCtx.sourceFilter)}>All sources</button>
                    {#each sourceChips as [id, n]}
                      <button class="ctxitem mono" class:active={searchCtx.sourceFilter === id} title={id} onclick={() => pickSource(id)}>{sourceName(id)} <span class="n">{n}</span></button>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}

            <!-- legend overlay (bottom-left): entity palette + edge styles + counts -->
            <div class="overlay legend">
              <div class="swatches">
                {#each ETYPES as t}
                  <span class="sw"><span class="dot" style="background:var(--etype-{t})"></span>{t}</span>
                {/each}
              </div>
              <div class="lrow"><span class="lline solid"></span> asserted (operator)</div>
              <div class="lrow"><span class="lline dashed"></span> derived (read-only)</div>
              <div class="lrow lcount">{graphCtx.nodes.length} nodes · {graphCtx.edges.length} edges</div>
            </div>

            <!-- inspector overlay (top-right): full entity detail, scrolls internally -->
            {#if selNode}
              <div class="overlay inspector">
                <EntityDetail entity={selNode} fields={selNode.fields} sourceName={graphSourceName} onClose={() => (selNode = null)} />
              </div>
            {/if}
          </div>
        {/if}
      {/if}
    {/if}
  </div>
</main>

{#if modal}
  <EdgeModal
    mode={modal.mode}
    src={modal.src}
    dst={modal.dst}
    edge={modal.edge}
    busy={graphCtx.mutating}
    error={graphCtx.mutateError}
    onConfirm={confirmModal}
    onCancel={closeModal}
  />
{/if}

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .count { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  /* The ONE vertical scroll region (Phase-1 scroll fix). Children never shrink so
     result groups grow to content and the whole column scrolls. */
  .body { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }
  .body > * { flex: 0 0 auto; }

  .searchbar { display: flex; gap: 10px; }
  .qinput {
    flex: 1 1 auto; min-width: 0; height: 34px; padding: 0 12px;
    background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius);
    color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-13); letter-spacing: var(--tracking-data);
  }
  .qinput::placeholder { color: var(--text-faint); }
  .qinput:focus { outline: none; border-color: var(--accent); }

  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  kbd { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 0 5px; }

  .facets { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    display: inline-flex; align-items: center; gap: 6px; max-width: 100%;
    background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius);
    color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    padding: 4px 9px; cursor: pointer; transition: border-color 120ms ease, background 120ms ease;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .chip.mono { font-family: var(--font-mono); }
  .chip:hover { border-color: var(--accent); }
  .chip.active { border-color: var(--accent); background: var(--accent-fill); color: var(--accent-text); }
  .chip .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .chip.active .n { color: var(--accent-text); }

  .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .toolbar-right { display: flex; align-items: center; gap: 8px; }
  .tbtn { height: 28px; display: inline-flex; align-items: center; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-12); padding: 0 10px; cursor: pointer; transition: border-color 120ms ease, background 120ms ease; }
  .tbtn:hover { border-color: var(--accent); }
  .tbtn.on { border-color: var(--accent); background: var(--accent-fill); color: var(--accent-text); }

  .layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
  .results { min-width: 0; display: flex; flex-direction: column; gap: 14px; }

  .rframe { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: visible; }
  .more { display: flex; justify-content: center; padding: 2px 0; }

  /* Full-bleed graph: the canvas fills (almost) the whole viewport and the legend
     + inspector float on top (VirusTotal-style), so the graph owns the screen. */
  .gwrap { position: relative; height: calc(100dvh - 200px); min-height: 520px; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; background: var(--surface); }

  .overlay { position: absolute; z-index: 2; border: 1px solid var(--border-strong); border-radius: var(--radius); background: rgba(12, 13, 16, 0.9); backdrop-filter: blur(3px); }
  .legend { left: 10px; bottom: 10px; display: flex; flex-direction: column; gap: 6px; padding: 9px 11px; max-width: 340px; }
  .lrow { display: flex; align-items: center; gap: 8px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); }
  .lrow.lcount { color: var(--text-faint); margin-top: 2px; }
  .lline { width: 22px; height: 0; border-top: 2px solid var(--edge-asserted); }
  .lline.dashed { border-top-style: dashed; border-top-color: var(--edge-derived); }

  /* Inspector floats over the graph; EntityDetail brings its own panel chrome so
     the wrapper is just position + scroll (a long message body scrolls here). */
  .inspector { top: 10px; right: 10px; width: 360px; max-width: calc(100% - 20px); max-height: calc(100% - 20px); overflow-y: auto; background: transparent; border: none; backdrop-filter: none; box-shadow: 0 6px 24px rgba(0, 0, 0, 0.5); }

  .ghint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }

  /* Right-click facet menu, positioned at the pointer inside the canvas. */
  .ctxmenu { position: absolute; z-index: 5; min-width: 170px; max-height: calc(100% - 20px); overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding: 8px; background: rgba(12, 13, 16, 0.97); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 6px 24px rgba(0, 0, 0, 0.5); backdrop-filter: blur(3px); }
  .ctxsec { display: flex; flex-direction: column; gap: 3px; }
  .ctxlabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); padding: 2px 4px; }
  .ctxitem { display: flex; align-items: center; justify-content: space-between; gap: 10px; text-align: left; background: transparent; border: 1px solid transparent; border-radius: var(--radius-sm); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-12); padding: 4px 8px; cursor: pointer; }
  .ctxitem.mono { font-family: var(--font-mono); }
  .ctxitem:hover { background: var(--surface); border-color: var(--accent); }
  .ctxitem.active { background: var(--accent-fill); border-color: var(--accent); color: var(--accent-text); }
  .ctxitem .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .ctxitem.active .n { color: var(--accent-text); }

  .rail { position: sticky; top: 0; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .collapse { appearance: none; background: transparent; border: none; color: var(--text-faint); font-family: var(--font-mono); font-size: var(--fs-16); line-height: 1; cursor: pointer; padding: 0 4px; }
  .collapse:hover { color: var(--accent-text); }

  .fields { display: flex; flex-direction: column; gap: 10px; padding: 10px 12px 12px; }
  .fhint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); line-height: var(--lh-normal); }
  .fhint code { font-family: var(--font-mono); color: var(--accent-text); }
  .fgroup { display: flex; flex-direction: column; gap: 5px; }
  .fgroup-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-muted); }
  .fchips { display: flex; flex-wrap: wrap; gap: 6px; }
  .fchipwrap { display: inline-flex; align-items: center; gap: 3px; }
  .fchip {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm);
    color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data);
    padding: 3px 7px; cursor: pointer; transition: border-color 120ms ease, color 120ms ease;
  }
  .fchip:hover { border-color: var(--accent); color: var(--accent-text); }
  .pluschip { background: var(--accent-fill); border: 1px solid rgba(162, 89, 196, 0.4); border-radius: var(--radius-sm); color: var(--accent-text); font-family: var(--font-mono); font-size: var(--fs-11); padding: 3px 5px; cursor: pointer; }
  .pluschip:hover { background: var(--accent-fill-strong); }

  .swatches { display: flex; flex-wrap: wrap; gap: 8px; }
  .sw { display: inline-flex; align-items: center; gap: 5px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); }
  .sw .dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; border: 1px solid #000; }

  @media (max-width: 900px) {
    .layout { grid-template-columns: 1fr; }
    .rail { position: static; }
  }
</style>
