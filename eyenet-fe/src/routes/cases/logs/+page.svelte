<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import AuditRow from '$lib/components/AuditRow.svelte';
  import { caseCtx, logsView, loadCaseLogs } from '$lib/case.svelte.js';

  // External-anchor table. The mock's `target` ("ots+btc") column is dropped —
  // an Anchor has no such field; it carries a server signature over the head
  // pair instead. Both heads (audit + journal) are shown, since one anchors
  // the audit chain and the other the file-access journal.
  const ANCHOR_COLUMNS = [
    { key: 'seq', header: 'Seq', mono: true, width: '80px' },
    { key: 'auditHead', header: 'Audit head', mono: true },
    { key: 'journalHead', header: 'Journal head', mono: true },
    { key: 'anchoredAt', header: 'Anchored', mono: true, align: 'right', width: '180px' }
  ];

  let c = $derived(caseCtx.active);
  let v = $derived(logsView.verify);

  // The layout gate already blocks this view when no case is active; still,
  // only fetch once a case is in hand, and refetch when it changes.
  $effect(() => {
    if (c) loadCaseLogs(c.caseId);
  });
</script>

<main>
  <SectionHeader group="Cases" slug="logs" title="Audit log" />

  <div class="body">
    <div class="strip">
      <StatTile
        label="Chain"
        value={v ? (v.verified ? 'VERIFIED' : 'BROKEN') : '—'}
        tone={v ? (v.verified ? 'accent' : 'critical') : 'default'}
        sub={v ? 'hash-chained · tamper-evident' : ''} />
      <StatTile
        label="Entries checked"
        value={v ? v.entries.toLocaleString() : '—'}
        sub="/v1/audit/verify" />
      <StatTile
        label="External anchors"
        value={logsView.anchors.length}
        sub="signed witness records" />
    </div>

    {#if v && !v.verified}
      <div class="alert">
        <span class="flag">TAMPER</span>
        <span>Chain verification failed. First divergence at event
          <span class="mono">{v.brokenEventId}</span> — the row is flagged below.</span>
      </div>
    {/if}

    <Panel title="Audit trail · this case · immutable" class="grow">
      {#snippet action()}<span class="count">{logsView.audit.length} events</span>{/snippet}
      {#each logsView.audit as a}
        <AuditRow {...a} />
      {:else}
        <p class="pnote">
          {logsView.loading ? 'Loading…' : 'No audit events recorded for this case yet.'}
        </p>
      {/each}
    </Panel>

    <Panel title="External anchors · §5.9">
      {#snippet action()}<span class="count">{logsView.anchors.length} anchors</span>{/snippet}
      {#if logsView.anchors.length}
        <DataTable rowKey="seq" columns={ANCHOR_COLUMNS} rows={logsView.anchors} />
      {:else}
        <p class="pnote">
          {logsView.loading ? 'Loading…' : 'No external anchors written yet.'}
        </p>
      {/if}
    </Panel>

    {#if logsView.error}
      <p class="err">{logsView.error}</p>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 16px; padding: 16px 20px; overflow: auto; }

  .strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; flex: 0 0 auto; }

  .alert { flex: 0 0 auto; display: flex; align-items: center; gap: 10px; padding: 10px 14px; border: 1px solid var(--red-text); border-radius: var(--radius); background: var(--red-fill); font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); }
  .flag { font-family: var(--font-mono); font-size: var(--fs-11); font-weight: var(--fw-medium); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--red-text); }
  .mono { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); }

  :global(.panel.grow) { flex: 1 1 auto; }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .err { margin: 0; padding: 10px 14px; border: 1px solid var(--red-text); border-radius: var(--radius); background: var(--red-fill); font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text); }

  @media (max-width: 720px) { .strip { grid-template-columns: 1fr; } }
</style>
