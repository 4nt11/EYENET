<script>
  // Reusable two-pane "workbench": a selectable EntityList rail + a flush dossier
  // detail (accented head with a title + filter bar, then a scrolling body). The
  // /actors page is the reference consumer; crews/personas/etc. compose the same
  // shell by passing snippets.
  //
  //   <DossierLayout listLabel="Actors" {items} {selectedId} onSelect={...}
  //     selected={!!current} accent={isManual}>
  //     {#snippet title()}<span class="handle">@x</span>{/snippet}
  //     {#snippet filters()}<Dropdown .../> <Segmented .../>{/snippet}
  //     {#snippet head()}<div class="badges">…</div>{/snippet}
  //     {#snippet body()}…panels…{/snippet}
  //     {#snippet empty()}<p class="pnote">No match.</p>{/snippet}
  //   </DossierLayout>
  import EntityList from './EntityList.svelte';
  let {
    listLabel,
    items = [],
    selectedId = null,
    onSelect,
    onLoadMore = null,
    hasMore = false,
    accent = false,
    selected = false,
    title,
    filters,
    head,
    body,
    empty
  } = $props();
</script>

<EntityList label={listLabel} {items} {selectedId} {onSelect} {onLoadMore} {hasMore} />

<main class="dossier">
  <div class="dossier-head" class:accent>
    <div class="head-top">
      <div class="dh-title">{@render title?.()}</div>
      {#if filters}<div class="filters">{@render filters()}</div>{/if}
    </div>
    {#if selected && head}{@render head()}{/if}
  </div>
  <div class="body">
    {#if selected}{@render body?.()}{:else}{@render empty?.()}{/if}
  </div>
</main>

<style>
  main.dossier { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .dossier-head { flex: 0 0 auto; padding: 16px 20px 16px 22px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--border-strong); }
  .dossier-head.accent { border-left-color: var(--accent); }
  .head-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .dh-title { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
  .filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; flex: 1; min-width: 0; }
  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }

  /* Shared filter-bar helpers so consumers don't re-style the common bits. */
  .filters :global(.fcount) { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); white-space: nowrap; margin-right: 2px; }
</style>
