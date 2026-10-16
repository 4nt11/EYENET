<script>
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { CANDIDATES, CANDIDATE_COLUMNS } from '$lib/data.js';

  let selectedId = $state(CANDIDATES[0].id);
  let sel = $derived(CANDIDATES.find((c) => c.id === selectedId) ?? CANDIDATES[0]);
  const open = $derived(sel.state === 'pending' || sel.state === 'requested');

  let detail = $derived([
    { label: 'Candidate', value: sel.id },
    { label: 'Group', value: sel.group },
    { label: 'Platform', value: sel.platform },
    { label: 'State', value: sel.state.toUpperCase(), tone: sel.state === 'rejected' ? undefined : open ? 'accent' : undefined },
    { label: 'Mentions', value: String(sel.mentions) },
    { label: 'Discovered via', value: sel.via },
    { label: 'Discovered', value: sel.found }
  ]);
  const pending = CANDIDATES.filter((c) => c.state === 'pending' || c.state === 'requested').length;
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">Discovery</span><span class="sep">/</span><span class="slug">candidates</span></div>
      <h1>Candidate triage</h1>
    </div>
    <span class="pending-count">{pending} awaiting decision</span>
  </div>

  <div class="body">
    <div class="table-col">
      <DataTable rowKey="id" columns={CANDIDATE_COLUMNS} rows={CANDIDATES}
        selectedId={selectedId} onRowClick={(r) => (selectedId = r.id)} />
    </div>

    <div class="detail-col">
      <EvidencePanel title={`Candidate · ${sel.id}`} items={detail} labelWidth={110} />
      <div class="actions">
        <div class="actions-label">Triage</div>
        <div class="actions-row">
          {#if open}
            <Button variant="primary" size="sm">Approve</Button>
            <Button variant="ghost" size="sm">Park</Button>
            <Button variant="destructive" size="sm">Reject</Button>
          {:else}
            <Button variant="ghost" size="sm">Retry</Button>
            <span class="settled">Already {sel.state}.</span>
          {/if}
        </div>
        {#if sel.state === 'requested'}
          <p class="hint">Approval-gated join (invite-link) · approving flips REQUESTED → JOINED once membership is confirmed.</p>
        {/if}
      </div>
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { flex: 0 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group, .sep { color: var(--text-faint); }
  .group { text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }
  .pending-count { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; }
  .actions { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .actions-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .actions-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .settled { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .hint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
