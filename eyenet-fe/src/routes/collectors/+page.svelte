<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { COLLECTORS, COLLECTOR_COLUMNS } from '$lib/data.js';

  let selectedId = $state(COLLECTORS[0].id);
  let sel = $derived(COLLECTORS.find((c) => c.id === selectedId) ?? COLLECTORS[0]);
  const running = COLLECTORS.filter((c) => c.state === 'running').length;

  let detail = $derived([
    { label: 'Collector', value: sel.id },
    { label: 'Kind', value: sel.kind },
    { label: 'State', value: sel.state.toUpperCase(), tone: sel.state === 'degraded' ? 'accent' : undefined },
    { label: 'Identity', value: sel.identity },
    { label: 'Groups', value: String(sel.memberships) },
    { label: 'Heartbeat', value: sel.heartbeat }
  ]);
</script>

<main>
  <SectionHeader group="Discovery" slug="collectors" title="Collector fleet">
    <span class="fleet">{running}/{COLLECTORS.length} running</span>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      <DataTable rowKey="id" columns={COLLECTOR_COLUMNS} rows={COLLECTORS}
        selectedId={selectedId} onRowClick={(r) => (selectedId = r.id)} />
    </div>

    <div class="detail-col">
      <EvidencePanel title={`Collector · ${sel.id}`} items={detail} labelWidth={100} />
      <div class="actions">
        <div class="actions-label">Fleet control</div>
        <div class="actions-row">
          {#if sel.state === 'stopped'}
            <Button variant="primary" size="sm">Start</Button>
          {:else}
            <Button variant="ghost" size="sm">Stop</Button>
          {/if}
          <Button variant="destructive" size="sm">Delete</Button>
        </div>
        {#if sel.state === 'degraded'}
          <p class="hint">Degraded: reconnecting to platform. It will resume on the next successful heartbeat.</p>
        {/if}
      </div>
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .fleet { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-muted); }

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; }

  .actions { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .actions-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .actions-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .hint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
