<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { collectorCtx, collectorView, observedTone, loadCollectors, loadCollectorDetail, collectorAction } from '$lib/collector.svelte.js';

  // Columns are the fields /v1/collectors returns. Single mock `state` is split
  // into observed (the badge) + desired; `degraded` isn't a real enum value.
  const COLUMNS = [
    { key: 'name', header: 'Collector', mono: true, width: '170px' },
    { key: 'kind', header: 'Kind', mono: true, width: '90px' },
    { key: 'observed', header: 'State', badge: true, tone: observedTone, width: '100px' },
    { key: 'desired', header: 'Desired', mono: true, width: '90px' },
    { key: 'heartbeat', header: 'Heartbeat', mono: true, align: 'right', width: '180px' }
  ];

  let selectedId = $state(null);
  let sel = $derived(collectorCtx.list.find((c) => c.id === selectedId) ?? collectorCtx.list[0] ?? null);

  // Fleet counters from /v1/collectors/health (fall back to the loaded list).
  let running = $derived(collectorCtx.fleet?.counts_by_observed_state?.running ?? collectorCtx.list.filter((c) => c.observed === 'running').length);
  let total = $derived(collectorCtx.fleet?.total ?? collectorCtx.list.length);

  let detail = $derived(
    sel
      ? [
          { label: 'Collector', value: sel.name },
          { label: 'ID', value: sel.id },
          { label: 'Kind', value: sel.kind },
          { label: 'Desired', value: sel.desired },
          { label: 'Observed', value: sel.observed, tone: sel.observed === 'running' ? 'accent' : sel.observed === 'crashed' ? 'critical' : undefined },
          { label: 'Identity', value: collectorView.identity },
          { label: 'Groups', value: String(collectorView.groups) },
          { label: 'Restarts', value: String(sel.restartCount) },
          { label: 'Heartbeat', value: sel.heartbeat }
        ]
      : []
  );

  $effect(() => {
    if (sel) loadCollectorDetail(sel.id);
  });

  onMount(loadCollectors);
</script>

<main>
  <SectionHeader group="Discovery" slug="collectors" title="Collector fleet">
    <span class="fleet">{running}/{total} running</span>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      {#if collectorCtx.list.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={collectorCtx.list}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !collectorCtx.loaded}Loading…{:else if collectorCtx.error}Could not load collectors: {collectorCtx.error}{:else}No collectors configured.{/if}
        </p>
      {/if}
    </div>

    {#if sel}
      <div class="detail-col">
        <EvidencePanel title={`Collector · ${sel.name}`} items={detail} labelWidth={100} />
        <div class="actions">
          <div class="actions-label">Fleet control</div>
          <div class="actions-row">
            {#if sel.observed === 'stopped'}
              <Button variant="primary" size="sm" disabled={collectorView.submitting} onclick={() => collectorAction(sel.id, 'start')}>Start</Button>
            {:else}
              <Button variant="ghost" size="sm" disabled={collectorView.submitting} onclick={() => collectorAction(sel.id, 'stop')}>Stop</Button>
            {/if}
            <Button variant="destructive" size="sm" disabled={collectorView.submitting} onclick={() => collectorAction(sel.id, 'delete')}>Delete</Button>
          </div>
          {#if collectorView.lastError}
            <p class="hint err">Last error: {collectorView.lastError}</p>
          {:else if sel.observed === 'crashed' || sel.observed === 'cooling'}
            <p class="hint">{sel.observed === 'cooling' ? 'Cooling down after a fault; the supervisor will retry.' : 'Crashed. The supervisor will restart it per policy.'}</p>
          {/if}
          {#if collectorView.submitMsg}<p class="submitmsg">{collectorView.submitMsg}</p>{/if}
        </div>
      </div>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .fleet { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-muted); }

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .actions { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .actions-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .actions-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .hint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }
  .hint.err { color: var(--red-text); }
  .submitmsg { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
