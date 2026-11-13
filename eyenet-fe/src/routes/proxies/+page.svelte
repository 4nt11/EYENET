<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import Dropdown from '$lib/components/Dropdown.svelte';
  import ProxyPoolCreateDialog from '$lib/components/ProxyPoolCreateDialog.svelte';
  import {
    poolCtx, proxyCtx,
    loadPools, createPool, deletePool,
    loadProxies, addProxy, bulkAddProxies, updateProxyState, deleteProxy, revealSecret
  } from '$lib/proxies.svelte.js';

  const KINDS = ['socks5', 'http', 'https', 'mtproxy'];
  const STATES = ['active', 'cooling', 'burned', 'disabled'];

  const COLUMNS = [
    { key: 'name', header: 'Pool', mono: true, width: '220px' },
    { key: 'kindHint', header: 'Kind', mono: true, width: '90px' },
    { key: 'description', header: 'Description', mono: true },
    { key: 'created', header: 'Created', mono: true, align: 'right', width: '180px' }
  ];

  let selectedId = $state(null);
  let sel = $derived(poolCtx.list.find((p) => p.id === selectedId) ?? poolCtx.list[0] ?? null);
  let proxies = $derived(sel ? (proxyCtx.byPool[sel.id] ?? []) : []);

  $effect(() => {
    if (sel && proxyCtx.byPool[sel.id] === undefined) loadProxies(sel.id);
  });

  const stateCount = (s) => proxies.filter((p) => p.state === s).length;
  let detail = $derived(
    sel
      ? [
          { label: 'Pool', value: sel.name },
          { label: 'ID', value: sel.id },
          { label: 'Kind hint', value: sel.kindHint || '-' },
          { label: 'Description', value: sel.description || '-' },
          { label: 'Proxies', value: String(proxies.length) },
          { label: 'Active', value: String(stateCount('active')), tone: 'accent' },
          { label: 'Burned', value: String(stateCount('burned')), tone: stateCount('burned') ? 'critical' : undefined },
          { label: 'Created', value: sel.created }
        ]
      : []
  );

  let createOpen = $state(false);

  // Dialog callback: raw API payload shape in, mapped-pool out so we can
  // immediately select the new row. Returns truthy = close the modal.
  async function handleCreatePool(payload) {
    const p = await createPool({
      name: payload.name,
      kindHint: payload.kind_hint,
      description: payload.description
    });
    selectedId = p.id;
    return true;
  }

  async function removePool() {
    if (!sel) return;
    if (!confirm(`Delete pool "${sel.name}"? Only works if it is empty.`)) return;
    try {
      await deletePool(sel.id);
      selectedId = null;
    } catch (e) {
      alert(e.message ?? String(e));
    }
  }

  let addKind = $state('socks5');
  let addHost = $state('');
  let addPort = $state('1080');
  let addSecret = $state('');
  let addSource = $state('');
  let addMsg = $state('');

  async function submitProxy() {
    if (!sel || !addHost.trim() || !addPort) return;
    try {
      await addProxy(sel.id, {
        kind: addKind,
        host: addHost.trim(),
        port: addPort,
        secret: addSecret || null,
        source: addSource.trim() || null,
        notes: null
      });
      addHost = ''; addSecret = ''; addSource = ''; addMsg = '';
    } catch (e) {
      addMsg = e.message ?? String(e);
    }
  }

  let bulkOpen = $state(false);
  let bulkLines = $state('');
  let bulkDefaultKind = $state('socks5');
  let bulkSource = $state('');

  async function submitBulk() {
    if (!sel || !bulkLines.trim()) return;
    const lines = bulkLines.split(/\r?\n/).filter((l) => l.trim());
    try {
      await bulkAddProxies(sel.id, {
        lines, defaultKind: bulkDefaultKind, source: bulkSource.trim() || null
      });
      bulkLines = '';
    } catch (e) {
      alert(e.message ?? String(e));
    }
  }

  async function doReveal(p) {
    try {
      const s = await revealSecret(p.id);
      alert(s ? `Credential for ${p.host}:${p.port}:\n\n${s}` : 'No credential set');
    } catch (e) {
      alert(e.message ?? String(e));
    }
  }

  async function flipState(p, next) {
    const reason = next === 'burned' ? prompt('Reason (optional):') ?? null : null;
    await updateProxyState(p.id, next, reason);
  }

  async function dropProxy(p) {
    if (!confirm(`Delete ${p.host}:${p.port}?`)) return;
    await deleteProxy(p.id, p.poolId);
  }

  onMount(loadPools);
</script>

<main>
  <SectionHeader group="System" slug="proxies" title="Proxy pools">
    <span class="count">{poolCtx.list.length} pool{poolCtx.list.length === 1 ? '' : 's'}</span>
    <Button variant="primary" size="sm" onclick={() => (createOpen = true)}>New pool</Button>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      {#if poolCtx.list.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={poolCtx.list}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !poolCtx.loaded}Loading...{:else if poolCtx.error}Could not load pools: {poolCtx.error}{:else}No proxy pools yet. Create one above.{/if}
        </p>
      {/if}
    </div>

    {#if sel}
      <div class="detail-col">
        <EvidencePanel title={`Pool · ${sel.name}`} items={detail} labelWidth={110} />

        <div class="actions">
          <div class="actions-label">Pool actions</div>
          <div class="actions-row">
            <Button variant="destructive" size="sm" onclick={removePool}>Delete pool</Button>
            <span class="hint">Only works when the pool has zero proxies.</span>
          </div>
        </div>

        <div class="actions">
          <div class="actions-label">Add a proxy</div>
          <div class="add-grid">
            <Dropdown
              minWidth="110px"
              options={KINDS.map((k) => ({ v: k, l: k }))}
              bind:value={addKind}
            />
            <input class="in" placeholder="host" bind:value={addHost} />
            <input class="in" placeholder="port" bind:value={addPort} inputmode="numeric" pattern="[0-9]*" maxlength="5" />
          </div>
          <input class="in" placeholder="user:pass (or MTProxy hex secret, optional)" bind:value={addSecret} />
          <div class="actions-row">
            <input class="in" placeholder="source tag (optional)" bind:value={addSource} />
            <Button variant="primary" size="sm" disabled={!addHost.trim()} onclick={submitProxy}>Add</Button>
          </div>
          {#if addMsg}<p class="err">{addMsg}</p>{/if}
        </div>

        <div class="actions">
          <div class="actions-label">
            <button class="disclosure" onclick={() => (bulkOpen = !bulkOpen)}>
              {bulkOpen ? 'v' : '>'} Bulk import
            </button>
          </div>
          {#if bulkOpen}
            <p class="hint">
              One per line. <code>socks5://host:port</code>, <code>socks5://user:pass@host:port</code>,
              <code>http://...</code>, <code>mtproto://host:port?secret=HEX</code>,
              <code>host:port</code>, <code>host:port:user:pass</code>.
            </p>
            <textarea class="in mono" rows="8" placeholder="paste proxies..." bind:value={bulkLines}></textarea>
            <div class="actions-row">
              <Dropdown
                minWidth="140px"
                options={KINDS.map((k) => ({ v: k, l: `default ${k}` }))}
                bind:value={bulkDefaultKind}
              />
              <input class="in" placeholder="source tag (e.g. shady-paste-20261112)" bind:value={bulkSource} />
              <Button variant="primary" size="sm" disabled={!bulkLines.trim()} onclick={submitBulk}>Import</Button>
            </div>
            {#if proxyCtx.lastResult}
              <p class="hint">
                Inserted <b>{proxyCtx.lastResult.inserted}</b>,
                duplicates <b>{proxyCtx.lastResult.skipped_duplicate}</b>,
                rejected <b>{proxyCtx.lastResult.rejected.length}</b>.
              </p>
              {#if proxyCtx.lastResult.rejected.length}
                <details><summary>rejected lines</summary>
                  <ul class="rej">{#each proxyCtx.lastResult.rejected as r}<li>{r}</li>{/each}</ul>
                </details>
              {/if}
            {/if}
          {/if}
        </div>

        <div class="actions">
          <div class="actions-label">Proxies <span class="hint">({proxies.length})</span></div>
          {#if proxyCtx.loading[sel.id]}
            <p class="hint">Loading...</p>
          {:else if !proxies.length}
            <p class="hint">No proxies in this pool yet.</p>
          {:else}
            <div class="proxy-list">
              {#each proxies as p (p.id)}
                <div class="prow">
                  <div class="meta">
                    <span class="kind">{p.kind}</span>
                    <span class="hostport">{p.host}:{p.port}</span>
                    <span class="badge state-{p.state}">{p.state}</span>
                    {#if p.hasSecret}<span class="badge auth">auth</span>{/if}
                    {#if p.source}<span class="src">{p.source}</span>{/if}
                    {#if p.boundIdentityId}<span class="bound">sticky-bound</span>{/if}
                  </div>
                  {#if p.lastError}<div class="rowerr">{p.lastError}</div>{/if}
                  <div class="rowbtns">
                    {#if p.hasSecret}<Button variant="ghost" size="sm" onclick={() => doReveal(p)}>Reveal</Button>{/if}
                    {#each STATES.filter((s) => s !== p.state) as s}
                      <Button variant="ghost" size="sm" onclick={() => flipState(p, s)}>{s}</Button>
                    {/each}
                    <Button variant="destructive" size="sm" onclick={() => dropProxy(p)}>Delete</Button>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </div>
    {/if}
  </div>

  <ProxyPoolCreateDialog bind:open={createOpen} onconfirm={handleCreatePool} />
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .count { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-muted); }

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(360px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 12px; min-height: 0; overflow: auto; padding-right: 2px; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .actions { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .actions-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .actions-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .actions-row > .in { flex: 1 1 140px; min-width: 0; }
  .add-grid { display: grid; grid-template-columns: 110px minmax(0, 1fr) 100px; gap: 8px; }
  .hint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }
  .hint code { background: var(--surface); padding: 1px 5px; border-radius: 4px; font-family: var(--font-mono); }
  .err { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--red-text); }

  .in { box-sizing: border-box; width: 100%; min-width: 0; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; appearance: textfield; -moz-appearance: textfield; }
  /* Kill the browser's number-input spinner regardless of input type.
     Firefox still renders a spinner on inputmode=numeric + pattern in
     some versions; webkit renders one on type=number. Belt-and-suspenders. */
  .in::-webkit-outer-spin-button,
  .in::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
  .in.short { width: 140px; flex: 0 0 auto; }
  .in.mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  .in:focus { outline: none; border-color: var(--accent); }

  .disclosure { background: none; border: 0; padding: 0; color: inherit; font: inherit; letter-spacing: inherit; text-transform: inherit; cursor: pointer; }

  .proxy-list { display: flex; flex-direction: column; gap: 6px; }
  .prow { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; align-items: center; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
  .meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-family: var(--font-mono); font-size: var(--fs-12); min-width: 0; }
  .kind { background: var(--panel); padding: 1px 6px; border-radius: 4px; text-transform: uppercase; font-size: var(--fs-10); color: var(--text-secondary); }
  .hostport { color: var(--text-body); word-break: break-all; }
  .badge { font-size: var(--fs-10); padding: 1px 6px; border-radius: 4px; text-transform: uppercase; }
  .badge.state-active { background: color-mix(in srgb, var(--accent) 20%, transparent); color: var(--accent-text); }
  .badge.state-cooling { background: color-mix(in srgb, #ffb400 20%, transparent); color: #ffd37a; }
  .badge.state-burned { background: var(--red-bg); color: var(--red-text); }
  .badge.state-disabled { background: var(--panel); color: var(--text-faint); }
  .badge.auth { background: var(--panel); color: var(--text-faint); }
  .src { font-size: var(--fs-10); color: var(--text-faint); }
  .bound { font-size: var(--fs-10); color: var(--accent-text); }
  .rowerr { grid-column: 1 / -1; color: var(--red-text); font-family: var(--font-mono); font-size: var(--fs-11); }
  .rowbtns { display: flex; gap: 4px; flex-wrap: wrap; }
  .rej { margin: 4px 0 0; padding-left: 18px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
