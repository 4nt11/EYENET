<script>
  import { onMount } from 'svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { identityCtx, identityView, identityTone, loadIdentities, loadIdentityDetail, identityAction, freezeAll } from '$lib/identity.svelte.js';

  // Columns are the fields /v1/identities returns. No `platform` or `claimed by`
  // (the read schema has neither; platform would need a source join, and there
  // is no claimed_by field). OPSEC fields never come over the wire.
  const COLUMNS = [
    { key: 'name', header: 'Identity', mono: true, width: '190px' },
    { key: 'role', header: 'Role', mono: true, width: '100px' },
    { key: 'state', header: 'State', badge: true, tone: identityTone, width: '100px' },
    { key: 'lastUsed', header: 'Last used', mono: true, align: 'right', width: '180px' }
  ];

  let selectedId = $state(null);
  let sel = $derived(identityCtx.list.find((i) => i.id === selectedId) ?? identityCtx.list[0] ?? null);

  let detail = $derived(
    sel
      ? [
          { label: 'Identity', value: sel.name },
          { label: 'ID', value: sel.id },
          { label: 'Role', value: sel.role },
          { label: 'State', value: sel.state, tone: sel.state === 'burned' ? 'critical' : sel.state === 'in_use' ? 'accent' : undefined },
          { label: 'Source', value: sel.sourceId.slice(0, 8) },
          { label: 'Last used', value: sel.lastUsed },
          { label: 'Cooldown', value: identityView.cooldown != null ? `${identityView.cooldown}s` : '—' },
          ...(identityView.notes ? [{ label: 'Notes', value: identityView.notes, mono: false }] : [])
        ]
      : []
  );

  let reason = $state('');

  $effect(() => {
    if (sel) loadIdentityDetail(sel.id);
  });

  onMount(loadIdentities);

  async function act(action) {
    if (!reason.trim() || !sel) return;
    await identityAction(sel.id, action, reason.trim());
    reason = '';
  }

  function doFreezeAll() {
    const r = window.prompt('Reason for freezing ALL identities:');
    if (r && r.trim()) freezeAll(r.trim());
  }
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">System</span><span class="sep">/</span><span class="slug">identities</span></div>
      <h1>Identity pool</h1>
    </div>
    <Button variant="destructive" size="sm" disabled={identityView.submitting || !identityCtx.list.length} onclick={doFreezeAll}>Freeze all</Button>
  </div>

  <div class="body">
    <div class="table-col">
      {#if identityCtx.list.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={identityCtx.list}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !identityCtx.loaded}Loading…{:else if identityCtx.error}Could not load identities: {identityCtx.error}{:else}No identities in the pool.{/if}
        </p>
      {/if}
    </div>

    {#if sel}
      <div class="detail-col">
        <EvidencePanel title={`Identity · ${sel.name}`} items={detail} labelWidth={100} />
        <div class="actions">
          <div class="actions-label">Lifecycle</div>
          {#if sel.state !== 'burned'}
            <input class="field" type="text" bind:value={reason} placeholder="Reason (required)" disabled={identityView.submitting} />
          {/if}
          <div class="actions-row">
            {#if sel.state === 'available'}<Button variant="primary" size="sm" disabled={identityView.submitting || !reason.trim()} onclick={() => act('claim')}>Claim</Button>{/if}
            {#if sel.state === 'in_use'}<Button variant="ghost" size="sm" disabled={identityView.submitting || !reason.trim()} onclick={() => act('release')}>Release</Button>{/if}
            {#if sel.state !== 'burned' && sel.state !== 'frozen'}<Button variant="ghost" size="sm" disabled={identityView.submitting || !reason.trim()} onclick={() => act('freeze')}>Freeze</Button>{/if}
            {#if sel.state !== 'burned'}<Button variant="destructive" size="sm" disabled={identityView.submitting || !reason.trim()} onclick={() => act('burn')}>Burn</Button>{/if}
            {#if sel.state === 'burned'}<span class="terminal">Burned · terminal, no actions.</span>{/if}
          </div>
          {#if identityView.submitMsg}<p class="submitmsg">{identityView.submitMsg}</p>{/if}
        </div>
      </div>
    {/if}
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

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .actions { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .actions-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .field { width: 100%; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .field:focus { outline: none; border-color: var(--accent); }
  .field::placeholder { color: var(--text-faint); }
  .field:disabled { opacity: 0.6; }
  .actions-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .terminal { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .submitmsg { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
