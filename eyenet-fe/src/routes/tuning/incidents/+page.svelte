<script>
  import { onMount } from 'svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Button from '$lib/components/Button.svelte';
  import {
    incidentRuleCtx,
    loadIncidentRules,
    createIncidentRule,
    setIncidentRuleEnabled,
    deleteIncidentRule
  } from '$lib/incidentRule.svelte.js';

  const NOAUTH = new Set([401, 403]);

  const COLUMNS = [
    { key: 'name', header: 'Name', width: '160px' },
    { key: 'pattern', header: 'Pattern', mono: true },
    { key: 'label', header: 'Label', mono: true, width: '200px' },
    { key: 'weight', header: 'Wt', align: 'right', width: '56px', mono: true },
    { key: 'enabled', header: 'Enabled', align: 'right', width: '90px', badge: true, tone: (v) => (v === 'on' ? 'high' : 'critical') }
  ];

  let selectedId = $state(null);
  let showAdd = $state(false);
  let fName = $state('');
  let fPattern = $state('');
  let fLabel = $state('');
  let fWeight = $state(2);
  let fDesc = $state('');

  const rows = $derived(
    (incidentRuleCtx.list ?? []).map((r) => ({
      id: r.id,
      name: r.name,
      pattern: r.pattern,
      label: r.label,
      weight: r.weight,
      enabled: r.enabled ? 'on' : 'off'
    }))
  );
  const sel = $derived(incidentRuleCtx.list.find((r) => r.id === selectedId) ?? null);
  const canCreate = $derived(
    fName.trim().length > 0 && fPattern.trim().length > 0 && fLabel.trim().length > 0 && !incidentRuleCtx.busy
  );

  onMount(loadIncidentRules);

  async function submitAdd() {
    const ok = await createIncidentRule({
      name: fName.trim(),
      pattern: fPattern.trim(),
      label: fLabel.trim(),
      weight: Number(fWeight) || 2,
      description: fDesc.trim()
    });
    if (ok) {
      fName = '';
      fPattern = '';
      fLabel = '';
      fDesc = '';
      showAdd = false;
    }
  }

  async function toggleSel() {
    if (sel) await setIncidentRuleEnabled(sel.id, !sel.enabled);
  }
  async function deleteSel() {
    if (sel) await deleteIncidentRule(sel.id);
  }
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">Tuning</span><span class="sep">/</span><span class="slug">incident rules</span></div>
      <h1>Incident detection rules</h1>
    </div>
    <Button variant="primary" size="sm" disabled={incidentRuleCtx.busy} onclick={() => (showAdd = !showAdd)}>
      {showAdd ? 'Cancel' : 'Add rule'}
    </Button>
  </div>

  <div class="body">
    <p class="lead">
      Operator RE2 rules layered ON TOP of the ML incident classifier: a pattern match
      forces an incident-taxonomy <code>label</code> with a <code>weight</code>, firing
      alongside the model heads. <code>label</code> must be a valid taxonomy head
      (the server rejects unknown labels and uncompilable patterns).
    </p>

    {#if showAdd}
      <form class="add" onsubmit={(e) => { e.preventDefault(); if (canCreate) submitAdd(); }}>
        <label>Name<input type="text" bind:value={fName} placeholder="cc-dump" /></label>
        <label class="grow">Pattern (RE2)
          <input type="text" bind:value={fPattern} placeholder="(?i)\bfullz?\b" spellcheck="false" />
        </label>
        <label>Label<input type="text" bind:value={fLabel} placeholder="taxonomy head" /></label>
        <label class="wt">Weight<input type="number" min="1" max="5" bind:value={fWeight} /></label>
        <label>Description<input type="text" bind:value={fDesc} placeholder="optional" /></label>
        <Button variant="primary" size="sm" type="submit" disabled={!canCreate}>Create</Button>
      </form>
    {/if}

    {#if incidentRuleCtx.error_msg}<p class="err">{incidentRuleCtx.error_msg}</p>{/if}

    {#if incidentRuleCtx.list.length}
      <DataTable rowKey="id" columns={COLUMNS} rows={rows} {selectedId} onRowClick={(r) => (selectedId = r.id === selectedId ? null : r.id)} />
      <div class="actions">
        <span class="note">{rows.length} rules{sel ? ` · selected: ${sel.name}` : ''}</span>
        <span class="spacer"></span>
        <Button variant="ghost" size="sm" disabled={!sel || incidentRuleCtx.busy} onclick={toggleSel}>
          {sel && sel.enabled ? 'Disable' : 'Enable'}
        </Button>
        <Button variant="destructive" size="sm" disabled={!sel || incidentRuleCtx.busy} onclick={deleteSel}>Delete</Button>
      </div>
    {:else if incidentRuleCtx.loaded && NOAUTH.has(incidentRuleCtx.status)}
      <p class="note">Incident rules need a token authorised to read them. Sign in with the right scope.</p>
    {:else if incidentRuleCtx.loaded && incidentRuleCtx.error}
      <p class="note">Incident rules unavailable (<code>/v1/incident-rules</code> did not respond).</p>
    {:else if incidentRuleCtx.loaded}
      <p class="note">No incident rules on record.</p>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { flex: 0 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group { color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .sep, .group { color: var(--text-faint); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 16px 20px; }
  .lead { margin: 0 0 16px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); }
  .lead code, .note code { color: var(--accent-text); font-family: var(--font-mono); }
  .add { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px; margin-bottom: 16px; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
  .add label { display: flex; flex-direction: column; gap: 5px; font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .add label.grow { flex: 1; min-width: 220px; }
  .add label.wt { width: 72px; }
  .add input { font-family: var(--font-mono); font-size: var(--fs-12); padding: 6px 8px; background: var(--black); border: 1px solid var(--border); border-radius: var(--radius); color: var(--text); }
  .actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
  .spacer { flex: 1; }
  .note { margin: 12px 0 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .actions .note { margin: 0; }
  .err { margin: 12px 0 0; padding: 10px 12px; border: 1px solid var(--critical, #c0392b); border-radius: var(--radius); font-family: var(--font-mono); font-size: var(--fs-12); color: var(--critical, #e06c5a); }
</style>
