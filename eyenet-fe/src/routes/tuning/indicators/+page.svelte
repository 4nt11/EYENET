<script>
  import { onMount } from 'svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Button from '$lib/components/Button.svelte';
  import {
    indicatorRuleCtx,
    INDICATOR_KINDS,
    loadIndicatorRules,
    createIndicatorRule,
    setIndicatorRuleEnabled,
    deleteIndicatorRule
  } from '$lib/indicatorRule.svelte.js';

  const NOAUTH = new Set([401, 403]);

  const COLUMNS = [
    { key: 'kind', header: 'Kind', mono: true, width: '180px' },
    { key: 'pattern', header: 'Pattern', mono: true },
    { key: 'source', header: 'Source', width: '90px', badge: true, tone: (v) => (v === 'vendored' ? 'neutral' : 'high') },
    { key: 'enabled', header: 'Enabled', align: 'right', width: '90px', badge: true, tone: (v) => (v === 'on' ? 'high' : 'critical') }
  ];

  let selectedId = $state(null);
  let showAdd = $state(false);
  // new-rule form
  let fKind = $state(INDICATOR_KINDS[0]);
  let fPattern = $state('');
  let fFold = $state(true);
  let fDesc = $state('');

  const rows = $derived(
    (indicatorRuleCtx.list ?? []).map((r) => ({
      id: r.id,
      kind: r.kind,
      pattern: r.pattern,
      source: r.vendored ? 'vendored' : 'custom',
      enabled: r.enabled ? 'on' : 'off'
    }))
  );
  const sel = $derived(indicatorRuleCtx.list.find((r) => r.id === selectedId) ?? null);
  const canCreate = $derived(fPattern.trim().length > 0 && !indicatorRuleCtx.busy);

  onMount(loadIndicatorRules);

  async function submitAdd() {
    const ok = await createIndicatorRule({
      kind: fKind,
      pattern: fPattern.trim(),
      fold_case: fFold,
      description: fDesc.trim()
    });
    if (ok) {
      fPattern = '';
      fDesc = '';
      showAdd = false;
    }
  }

  async function toggleSel() {
    if (sel) await setIndicatorRuleEnabled(sel.id, !sel.enabled);
  }
  async function deleteSel() {
    if (sel && !sel.vendored) await deleteIndicatorRule(sel.id);
  }
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">Tuning</span><span class="sep">/</span><span class="slug">indicator rules</span></div>
      <h1>Indicator extraction rules</h1>
    </div>
    <Button variant="primary" size="sm" disabled={indicatorRuleCtx.busy} onclick={() => (showAdd = !showAdd)}>
      {showAdd ? 'Cancel' : 'Add custom rule'}
    </Button>
  </div>

  <div class="body">
    <p class="lead">
      The ruleset the collectors run per message to extract operational infrastructure
      (wallets, contact handles, email, PGP, Session, Tox). Matches dedup into the
      artifact store and surface in <code>/v1/search</code> by kind. Vendored defaults
      ship seeded — disable them, never delete; add your own custom patterns (RE2).
    </p>

    {#if showAdd}
      <form class="add" onsubmit={(e) => { e.preventDefault(); if (canCreate) submitAdd(); }}>
        <label>Kind
          <input type="text" list="indicator-kinds" bind:value={fKind} spellcheck="false" placeholder="wallet_btc, ipv4, discord_handle" />
          <datalist id="indicator-kinds">
            {#each INDICATOR_KINDS as k}<option value={k}></option>{/each}
          </datalist>
        </label>
        <label class="grow">Pattern (RE2)
          <input type="text" bind:value={fPattern} placeholder="\bT[1-9A-HJ-NP-Za-km-z]{'{33}'}\b" spellcheck="false" />
        </label>
        <label>Description
          <input type="text" bind:value={fDesc} placeholder="optional" />
        </label>
        <label class="chk"><input type="checkbox" bind:checked={fFold} /> fold case</label>
        <Button variant="primary" size="sm" type="submit" disabled={!canCreate}>Create</Button>
      </form>
    {/if}

    {#if indicatorRuleCtx.error_msg}<p class="err">{indicatorRuleCtx.error_msg}</p>{/if}

    {#if indicatorRuleCtx.list.length}
      <DataTable rowKey="id" columns={COLUMNS} rows={rows} {selectedId} onRowClick={(r) => (selectedId = r.id === selectedId ? null : r.id)} />
      <div class="actions">
        <span class="note">{rows.length} rules{sel ? ` · selected: ${sel.kind}` : ''}</span>
        <span class="spacer"></span>
        <Button variant="ghost" size="sm" disabled={!sel || indicatorRuleCtx.busy} onclick={toggleSel}>
          {sel && sel.enabled ? 'Disable' : 'Enable'}
        </Button>
        <Button variant="destructive" size="sm" disabled={!sel || sel.vendored || indicatorRuleCtx.busy} onclick={deleteSel}>
          Delete
        </Button>
      </div>
      {#if sel && sel.vendored}<p class="note hint">Vendored rules can't be deleted — disable instead (survives upgrades).</p>{/if}
    {:else if indicatorRuleCtx.loaded && NOAUTH.has(indicatorRuleCtx.status)}
      <p class="note">Indicator rules need a token authorised to read collector config. Sign in with the right scope.</p>
    {:else if indicatorRuleCtx.loaded && indicatorRuleCtx.error}
      <p class="note">Indicator rules unavailable (<code>/v1/indicators/rules</code> did not respond).</p>
    {:else if indicatorRuleCtx.loaded}
      <p class="note">No indicator rules on record.</p>
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
  .add label.grow { flex: 1; min-width: 240px; }
  .add label.chk { flex-direction: row; align-items: center; gap: 6px; text-transform: none; }
  .add input[type='text'], .add select { font-family: var(--font-mono); font-size: var(--fs-12); padding: 6px 8px; background: var(--black); border: 1px solid var(--border); border-radius: var(--radius); color: var(--text); }
  .actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
  .spacer { flex: 1; }
  .note { margin: 12px 0 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .actions .note { margin: 0; }
  .note.hint { color: var(--text-faint); }
  .err { margin: 12px 0 0; padding: 10px 12px; border: 1px solid var(--critical, #c0392b); border-radius: var(--radius); font-family: var(--font-mono); font-size: var(--fs-12); color: var(--critical, #e06c5a); }
</style>
