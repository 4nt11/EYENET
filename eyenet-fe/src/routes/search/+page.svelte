<script>
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { searchCtx, runSearch, loadMoreSearch, setTypeFilter, setSourceFilter } from '$lib/search.svelte.js';

  // Columns are the SearchHit fields. One Panel+DataTable per entity-type group
  // (DataTable has no grouping of its own).
  const COLUMNS = [
    { key: 'title', header: 'Title' },
    { key: 'subtitle', header: 'Subtitle' },
    { key: 'status', header: 'Status', mono: true, width: '120px' },
    { key: 'sourceShort', header: 'Source', mono: true, width: '110px' }
  ];

  // Ordered type labels so groups render in a stable, sensible order (any type
  // not listed falls to the end). entity_type ∈ actor|group|thread|message|
  // mention|artifact|persona|crew|case|document|attachment|incident.
  const TYPE_ORDER = ['actor', 'persona', 'crew', 'case', 'group', 'thread', 'message', 'mention', 'incident', 'document', 'attachment', 'artifact'];
  const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);

  // Best-effort deep-link map: not every entity_type has a detail screen. A type
  // absent here renders a non-navigating row (no pointer, no onRowClick).
  const ROUTE = {
    actor: (r) => `/actors?id=${r.id}`,
    persona: (r) => `/personas?id=${r.id}`,
    case: (r) => `/cases?id=${r.id}`,
    group: (r) => `/monitored-groups?id=${r.id}`,
    thread: (r) => `/monitored-groups?id=${r.id}`
  };

  // Read ?q= on mount and reactively whenever it changes (top-bar navigations
  // reuse this route).
  $effect(() => {
    const q = $page.url.searchParams.get('q') ?? '';
    runSearch(q);
  });

  // Group the loaded page by entity_type, honouring the active type facet.
  let groups = $derived.by(() => {
    const by = {};
    for (const r of searchCtx.items) {
      if (searchCtx.typeFilter && r.entityType !== searchCtx.typeFilter) continue;
      (by[r.entityType] ??= []).push(r);
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

  function navFor(type) {
    return ROUTE[type] ? (r) => goto(ROUTE[type](r)) : undefined;
  }
</script>

<main>
  <SectionHeader group="Investigate" slug="search" title="Search">
    <span class="count">
      {#if !searchCtx.q}idle{:else if searchCtx.total != null}{searchCtx.total} match{searchCtx.total === 1 ? '' : 'es'}{:else}{searchCtx.items.length} loaded{/if}
    </span>
  </SectionHeader>

  <div class="body">
    {#if !searchCtx.q}
      <p class="pnote">Enter a query in the top-bar search (or press <kbd>/</kbd>) to search across actors, personas, cases, groups, messages, documents and more.</p>
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
            <button class="chip mono" class:active={searchCtx.sourceFilter === id} title={id} onclick={() => setSourceFilter(id)}>{id.slice(0, 8)} <span class="n">{n}</span></button>
          {/each}
        </div>
      {/if}

      {#if groups.length}
        {#each groups as g}
          <Panel title={`${cap(g.type)} (${g.rows.length})`}>
            <DataTable rowKey="id" columns={COLUMNS} rows={g.rows} onRowClick={navFor(g.type)} />
          </Panel>
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
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .count { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  kbd { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 0 5px; }

  .facets { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius);
    color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    padding: 4px 9px; cursor: pointer; transition: border-color 120ms ease, background 120ms ease;
  }
  .chip.mono { font-family: var(--font-mono); }
  .chip:hover { border-color: var(--accent); }
  .chip.active { border-color: var(--accent); background: var(--accent-fill); color: var(--accent-text); }
  .chip .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .chip.active .n { color: var(--accent-text); }

  .more { display: flex; justify-content: center; padding: 2px 0; }
</style>
