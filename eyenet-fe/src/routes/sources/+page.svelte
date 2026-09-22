<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import { sourceCtx, sourceView, loadSources, loadSourceDetail } from '$lib/source.svelte.js';

  // Columns are the fields /v1/sources actually returns. No `state` badge and
  // no `lastIngest` — the API has no backing field for either (see PR notes).
  const SOURCE_COLUMNS = [
    { key: 'id', header: 'Source', mono: true, width: '260px' },
    { key: 'platform', header: 'Platform', mono: true, width: '90px' },
    { key: 'name', header: 'Name', mono: true },
    { key: 'domainCount', header: 'Domains', mono: true, align: 'right', width: '90px' },
    { key: 'created', header: 'Created', mono: true, align: 'right', width: '190px' }
  ];

  let selectedId = $state(null);
  let sel = $derived(sourceCtx.list.find((s) => s.id === selectedId) ?? sourceCtx.list[0] ?? null);

  let detail = $derived(
    sel
      ? [
          { label: 'Source', value: sel.id },
          { label: 'Platform', value: sel.platform, tone: 'accent' },
          { label: 'Name', value: sel.name },
          { label: 'Canonical URL', value: sel.canonicalUrl ?? '—' },
          { label: 'Created', value: sel.created },
          { label: 'Resolved artifacts', value: String(sourceView.resolvedCount) }
        ]
      : []
  );

  // Fetch the selected source's detail (active domains) whenever selection moves.
  $effect(() => {
    if (sel) loadSourceDetail(sel.id);
  });

  onMount(loadSources); // populate the list from /v1/sources
</script>

<main>
  <SectionHeader group="Discovery" slug="sources" title="Sources" />

  <div class="body">
    <div class="table-col">
      {#if sourceCtx.list.length}
        <DataTable rowKey="id" columns={SOURCE_COLUMNS} rows={sourceCtx.list}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !sourceCtx.loaded}Loading...{:else if sourceCtx.error}Could not load sources: {sourceCtx.error}{:else}No sources configured.{/if}
        </p>
      {/if}
    </div>

    <div class="detail-col">
      <EvidencePanel title={`Source · ${sel?.id ?? '—'}`} items={detail} labelWidth={120} />

      <Panel title={`Source domains · ${sourceView.domains.length}`} class="domains">
        {#if sourceView.domains.length}
          {#each sourceView.domains as d}
            <div class="drow"><span class="dname">{d}</span></div>
          {/each}
        {:else}
          <div class="empty">
            {#if sourceView.loading}Loading...{:else if sourceView.error}Could not load domains: {sourceView.error}{:else}No active domains for this source.{/if}
          </div>
        {/if}
      </Panel>
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }

  :global(.panel.domains) { flex: 0 0 auto; max-height: 200px; }
  .drow { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .drow:last-child { border-bottom: none; }
  .dname { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
