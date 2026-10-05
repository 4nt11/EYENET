<script>
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import {
    searchCtx, runSearch, loadMoreSearch, setTypeFilter, setSourceFilter, sourceName
  } from '$lib/search.svelte.js';

  // Columns are the SearchHit fields. One Panel+DataTable per entity-type group
  // (DataTable has no grouping of its own). `sourceName` resolves the raw hex
  // source_id to its human label (API-provided), falling back to the short id.
  const COLUMNS = [
    { key: 'title', header: 'Title' },
    { key: 'subtitle', header: 'Subtitle' },
    { key: 'status', header: 'Status', mono: true, width: '110px' },
    { key: 'sourceName', header: 'Source', mono: true, width: '150px' }
  ];

  // Ordered type labels so groups render in a stable, sensible order (any type
  // not listed falls to the end). entity_type ∈ actor|group|thread|message|
  // mention|artifact|persona|crew|case|document|attachment|incident.
  const TYPE_ORDER = ['actor', 'persona', 'crew', 'case', 'group', 'thread', 'message', 'mention', 'incident', 'document', 'attachment', 'artifact'];
  const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);

  // Best-effort deep-link map: not every entity_type has a detail screen. A type
  // absent here renders without an "Open" link in the detail panel.
  const ROUTE = {
    actor: (r) => `/actors?id=${r.id}`,
    persona: (r) => `/personas?id=${r.id}`,
    case: (r) => `/cases?id=${r.id}`,
    group: (r) => `/monitored-groups?id=${r.id}`,
    thread: (r) => `/monitored-groups?id=${r.id}`
  };
  const ROUTE_LABEL = { actor: 'Actors', persona: 'Personas', case: 'Cases', group: 'Monitored groups', thread: 'Monitored groups' };

  // Queryable-fields palette for the upcoming query language (Phase 1.5). Clicking
  // a field appends `field:` to the in-page box so the operator can compose a query.
  const QUERY_FIELDS = [
    { group: 'Message', fields: ['message.content', 'message.author'] },
    { group: 'Group', fields: ['group.title', 'group.status'] },
    { group: 'Forum', fields: ['forum.thread.author'] },
    { group: 'Actor', fields: ['actor.handle'] },
    { group: 'Artifact', fields: ['artifact.value'] },
    { group: 'Case', fields: ['case.title'] },
    { group: 'Document', fields: ['document.text'] }
  ];

  // In-page query box. Kept in sync with the URL ?q= so top-bar and in-page
  // searches stay coherent; Enter in either navigates (the $effect runs the fetch).
  let query = $state('');
  let inputEl;

  $effect(() => {
    const q = $page.url.searchParams.get('q') ?? '';
    query = q;
    runSearch(q);
  });

  function submitInPage(e) {
    if (e.key !== 'Enter') return;
    goto(`/search?q=${encodeURIComponent(query.trim())}`);
  }

  function insertField(f) {
    const cur = query.trimEnd();
    query = (cur ? cur + ' ' : '') + f + ':';
    inputEl?.focus();
  }

  // Group the loaded page by entity_type, honouring the active type facet, and
  // attach the human source name per row for the table's Source column.
  let groups = $derived.by(() => {
    const by = {};
    for (const r of searchCtx.items) {
      if (searchCtx.typeFilter && r.entityType !== searchCtx.typeFilter) continue;
      (by[r.entityType] ??= []).push({ ...r, sourceName: sourceName(r.sourceId) });
    }
    const present = Object.keys(by);
    present.sort((a, b) => {
      const ia = TYPE_ORDER.indexOf(a);
      const ib = TYPE_ORDER.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
    return present.map((t) => ({ type: t, rows: by[t] }));
  });

  let typeChips = $derived(
    Object.entries(searchCtx.byType).sort((a, b) => b[1] - a[1])
  );
  let sourceChips = $derived(
    Object.entries(searchCtx.bySource).filter(([id]) => id).sort((a, b) => b[1] - a[1])
  );

  // Row selection drives the detail side-panel (click a row to inspect it).
  let selectedId = $state(null);
  let sel = $derived(selectedId ? (searchCtx.items.find((x) => x.id === selectedId) ?? null) : null);
  // A selected row can carry an author/handle in its subtitle — surface it clearly.
  const HAS_HANDLE = new Set(['message', 'actor', 'thread', 'mention']);

  // Collapsible fields palette (per-viewer convenience only, no persistence needed).
  let fieldsOpen = $state(true);
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

      <div class="layout">
        <div class="results">
          {#if groups.length}
            {#each groups as g (g.type)}
              <section class="rgroup">
                <div class="rhead">
                  <span class="rlabel">{cap(g.type)}</span>
                  <span class="rcount">{g.rows.length}</span>
                </div>
                <DataTable
                  rowKey="id"
                  columns={COLUMNS}
                  rows={g.rows}
                  selectedId={sel?.id}
                  onRowClick={(r) => (selectedId = r.id)}
                  stickyHead
                  stickyTop="33px"
                  flat
                  fixed
                />
              </section>
            {/each}
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
              <button class="collapse" onclick={() => (fieldsOpen = !fieldsOpen)} aria-expanded={fieldsOpen} aria-label="Toggle query fields">
                {fieldsOpen ? '−' : '+'}
              </button>
            {/snippet}
            {#if fieldsOpen}
              <div class="fields">
                <p class="fhint">Click to insert <code>field:</code>. The query language (<code>field:value</code>, <code>==</code>, <code>!=</code>, AND/OR) arrives in Phase 1.5.</p>
                {#each QUERY_FIELDS as fg}
                  <div class="fgroup">
                    <div class="fgroup-label">{fg.group}</div>
                    <div class="fchips">
                      {#each fg.fields as f}
                        <button class="fchip" onclick={() => insertField(f)} title={`Insert ${f}:`}>{f}</button>
                      {/each}
                    </div>
                  </div>
                {/each}
              </div>
            {/if}
          </Panel>

          {#if sel}
            <div class="detail">
              <div class="detail-head">
                <Badge tone="high">{cap(sel.entityType)}</Badge>
                <button class="detail-close" onclick={() => (selectedId = null)} aria-label="Close detail">×</button>
              </div>
              <div class="dtitle">{sel.title || '—'}</div>
              {#if sel.subtitle}
                <div class="dfield">
                  <span class="dk">{HAS_HANDLE.has(sel.entityType) ? 'Author / handle' : 'Subtitle'}</span>
                  <span class="dv">{sel.subtitle}</span>
                </div>
              {/if}
              {#if sel.status}
                <div class="dfield"><span class="dk">Status</span><span class="dv mono">{sel.status}</span></div>
              {/if}
              <div class="dfield"><span class="dk">Source</span><span class="dv mono" title={sel.sourceId ?? ''}>{sourceName(sel.sourceId) || '—'}</span></div>
              <div class="dfield"><span class="dk">Entity id</span><span class="dv mono" title={sel.id}>{sel.id}</span></div>

              {#if ROUTE[sel.entityType]}
                <a class="dopen" href={ROUTE[sel.entityType](sel)}>Open in {ROUTE_LABEL[sel.entityType]} →</a>
              {:else}
                <p class="dnote">No dedicated detail screen for this entity type.</p>
              {/if}

              <!-- TODO(search-enrich): deeper correlations — persona membership, linkage
                   evidence, actor neighbors, crew — need new API data on the SearchHit
                   (or a per-entity detail fetch). Do NOT fabricate; wire once the backend
                   ships an enriched search-hit / detail endpoint. -->
            </div>
          {/if}
        </aside>
      </div>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .count { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  /* The ONE vertical scroll region. Children never shrink (flex:0 0 auto), so the
     result groups grow to their content and the whole column scrolls — instead of
     flexbox squishing each Panel into its own tiny scroll area (the old bug). */
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

  .layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
  .results { min-width: 0; display: flex; flex-direction: column; gap: 14px; }

  /* Framed group section. overflow:visible so the sticky head + the table's sticky
     <thead> can pin to the page scroll (.body), not to the section. */
  .rgroup { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: visible; }
  .rhead {
    position: sticky; top: 0; z-index: 3;
    height: 33px; display: flex; align-items: center; justify-content: space-between; gap: 10px;
    padding: 0 12px; background: var(--panel); border-bottom: 1px solid var(--border);
    border-radius: var(--radius) var(--radius) 0 0;
  }
  .rlabel { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .rcount { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); }

  .more { display: flex; justify-content: center; padding: 2px 0; }

  .rail { position: sticky; top: 0; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .collapse { appearance: none; background: transparent; border: none; color: var(--text-faint); font-family: var(--font-mono); font-size: var(--fs-16); line-height: 1; cursor: pointer; padding: 0 4px; }
  .collapse:hover { color: var(--accent-text); }

  .fields { display: flex; flex-direction: column; gap: 10px; padding: 10px 12px 12px; }
  .fhint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); line-height: var(--lh-normal); }
  .fhint code { font-family: var(--font-mono); color: var(--accent-text); }
  .fgroup { display: flex; flex-direction: column; gap: 5px; }
  .fgroup-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-muted); }
  .fchips { display: flex; flex-wrap: wrap; gap: 6px; }
  .fchip {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm);
    color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data);
    padding: 3px 7px; cursor: pointer; transition: border-color 120ms ease, color 120ms ease;
  }
  .fchip:hover { border-color: var(--accent); color: var(--accent-text); }

  .detail { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .detail-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .detail-close { appearance: none; background: transparent; border: none; color: var(--text-faint); font-size: var(--fs-18); line-height: 1; cursor: pointer; padding: 0 4px; }
  .detail-close:hover { color: var(--accent-text); }
  .dtitle { font-family: var(--font-sans); font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); word-break: break-word; }
  .dfield { display: flex; flex-direction: column; gap: 2px; }
  .dk { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .dv { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); word-break: break-word; }
  .dv.mono { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  .dopen { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); text-decoration: none; margin-top: 2px; }
  .dopen:hover { color: var(--link-hover); text-decoration: underline; }
  .dnote { margin: 2px 0 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }

  @media (max-width: 900px) {
    .layout { grid-template-columns: 1fr; }
    .rail { position: static; }
  }
</style>
