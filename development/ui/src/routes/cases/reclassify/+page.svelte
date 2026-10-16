<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Button from '$lib/components/Button.svelte';
  import ReclassifyDialog from '$lib/components/ReclassifyDialog.svelte';
  import { RECLASSIFICATIONS, RECLASS_COLUMNS } from '$lib/data.js';

  let reclassOpen = $state(false);
  // A promotion is normally launched from a document/attachment/observation; this
  // standalone entry uses a placeholder subject.
  const sample = { id: 'OBS-9912', kind: 'observation', classifier_tier: 'normal', effective_tier: 'restricted' };
</script>

<main>
  <SectionHeader group="Cases" slug="reclassify" title="Reclassify">
    <Button variant="primary" size="sm" onclick={() => (reclassOpen = true)}>New promotion</Button>
  </SectionHeader>

  <div class="body">
    <div class="card">
      <p class="lede">Promote-only. The classifier owns an immutable tier floor; an operator may only raise the effective
        tier via an override, never lower it. Every promotion needs an <code>admin:reclassify</code> grant, a signed
        body, and a reason, and is written to the audit chain.</p>
      <div class="rules">
        <span class="rule">normal → restricted → classified</span>
        <span class="rule">effective = max(classifier, override)</span>
        <span class="rule">enforced at endpoint · DB check · audit</span>
      </div>
    </div>

    <Panel title="Recent promotions">
      <DataTable rowKey="subject_id" columns={RECLASS_COLUMNS} rows={RECLASSIFICATIONS} />
    </Panel>
  </div>
</main>

<ReclassifyDialog bind:open={reclassOpen} subject={sample} onconfirm={(r) => console.log('reclassify', r)} />

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .body > :global(*) { margin-bottom: 16px; }

  .card { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 16px 18px; }
  .lede { margin: 0 0 12px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); max-width: 90ch; }
  code { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); background: var(--surface); padding: 1px 5px; border-radius: var(--radius-sm); }
  .rules { display: flex; flex-wrap: wrap; gap: 8px; }
  .rule { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 3px 8px; }
</style>
