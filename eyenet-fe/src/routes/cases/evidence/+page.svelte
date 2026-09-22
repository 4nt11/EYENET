<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import { caseCtx } from '$lib/case.svelte.js';
  import { evidenceCtx, tierTone, loadCaseObservations } from '$lib/evidence.svelte.js';

  // Case-scoped observation members. Columns come from the real ObservationSummary
  // — the mock `tier` (severity: critical/high/…) has no API backing and is
  // dropped; `sensitivity` is the real SensitivityTier.
  const COLUMNS = [
    { key: 'idShort', header: 'Observation', mono: true, width: '110px' },
    { key: 'kind', header: 'Kind', mono: true },
    { key: 'observed', header: 'Observed', mono: true, width: '160px' },
    { key: 'sensitivity', header: 'Sensitivity', badge: true, tone: tierTone, width: '120px' }
  ];

  let selectedId = $state(null);
  let sel = $derived(evidenceCtx.list.find((x) => x.id === selectedId) ?? evidenceCtx.list[0] ?? null);

  let detail = $derived(
    sel
      ? [
          { label: 'Observation', value: sel.id },
          { label: 'Kind', value: sel.kind },
          { label: 'Primitive', value: sel.primitive || '—' },
          { label: 'Observed', value: sel.observed },
          { label: 'Score', value: sel.scoreText },
          { label: 'Sensitivity', value: sel.sensitivity },
          ...(sel.attachmentBlobId ? [{ label: 'Attachment', value: sel.attachmentBlobId }] : [])
        ]
      : []
  );

  // Reload whenever the active case changes (caseCtx.active is set by the case
  // switcher). No active case → honest empty state, no fabricated list.
  $effect(() => {
    loadCaseObservations(caseCtx.active?.caseId ?? null);
  });
</script>

<main>
  <SectionHeader group="Cases" slug="evidence" title="Evidence">
    <span class="ctx">{caseCtx.active?.caseId ?? ''}</span>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      {#if !caseCtx.active}
        <p class="pnote">Enter a case to view its evidence.</p>
      {:else if evidenceCtx.list.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={evidenceCtx.list}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !evidenceCtx.loaded}Loading…{:else if evidenceCtx.error}Could not load evidence: {evidenceCtx.error}{:else}No observations attached to this case yet.{/if}
        </p>
      {/if}
    </div>
    {#if sel}
      <div class="detail-col">
        <EvidencePanel title={`Selected · ${sel.idShort}`} items={detail} />
      </div>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .ctx { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
