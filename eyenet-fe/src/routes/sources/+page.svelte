<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { SOURCES, SOURCE_COLUMNS } from '$lib/data.js';

  let selectedId = $state(SOURCES[0].id);
  let sel = $derived(SOURCES.find((s) => s.id === selectedId) ?? SOURCES[0]);

  let detail = $derived([
    { label: 'Source', value: sel.id },
    { label: 'Platform', value: sel.platform },
    { label: 'Name', value: sel.name },
    { label: 'State', value: sel.state.toUpperCase(), tone: sel.state === 'paused' ? undefined : 'accent' },
    { label: 'Last ingest', value: sel.lastIngest }
  ]);
</script>

<main>
  <SectionHeader group="Discovery" slug="sources" title="Sources">
    <Button variant="primary" size="sm">Add source</Button>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      <DataTable rowKey="id" columns={SOURCE_COLUMNS} rows={SOURCES}
        selectedId={selectedId} onRowClick={(r) => (selectedId = r.id)} />
    </div>

    <div class="detail-col">
      <EvidencePanel title={`Source · ${sel.id}`} items={detail} labelWidth={100} />

      <Panel title={`Source domains · ${sel.domains.length}`} class="domains">
        {#if sel.domains.length}
          {#each sel.domains as d}
            <div class="drow"><span class="dname">{d}</span><Button variant="quiet" size="sm">Remove</Button></div>
          {/each}
        {:else}
          <div class="empty">No domains configured.</div>
        {/if}
      </Panel>

      <div class="actions">
        <div class="actions-label">Source</div>
        <div class="actions-row">
          {#if sel.state === 'active'}
            <Button variant="ghost" size="sm">Pause</Button>
          {:else}
            <Button variant="primary" size="sm">Resume</Button>
          {/if}
          <Button variant="ghost" size="sm">Add domain</Button>
        </div>
      </div>
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

  .actions { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .actions-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .actions-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
