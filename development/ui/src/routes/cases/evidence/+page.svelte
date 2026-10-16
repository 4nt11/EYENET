<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import { EVIDENCE, EVIDENCE_COLUMNS, SELECTED_DETAIL } from '$lib/data.js';
  import { caseCtx } from '$lib/case.svelte.js';

  let selected = $state('ART-0091');
  let detail = $derived(SELECTED_DETAIL(selected));
</script>

<main>
  <SectionHeader group="Cases" slug="evidence" title="Evidence">
    <span class="ctx">{caseCtx.active?.caseId ?? ''}</span>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      <DataTable rowKey="id" columns={EVIDENCE_COLUMNS} rows={EVIDENCE}
        selectedId={selected} onRowClick={(r) => (selected = r.id)} />
    </div>
    <div class="detail-col">
      <EvidencePanel title={`Selected · ${selected}`} items={detail} />
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .ctx { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
