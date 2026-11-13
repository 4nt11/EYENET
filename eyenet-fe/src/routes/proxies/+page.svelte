<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Button from '$lib/components/Button.svelte';
  import {
    poolCtx, proxyCtx,
    loadPools, createPool, deletePool,
    loadProxies, addProxy, bulkAddProxies, updateProxyState, deleteProxy, revealSecret
  } from '$lib/proxies.svelte.js';

  const KINDS = ['socks5', 'http', 'https', 'mtproxy'];
  const STATES = ['active', 'cooling', 'burned', 'disabled'];

  // New pool form
  let newPoolName = $state('');
  let newPoolKind = $state('');
  let newPoolDesc = $state('');

  async function submitPool(e) {
    e.preventDefault();
    if (!newPoolName.trim()) return;
    const p = await createPool({
      name: newPoolName.trim(),
      kindHint: newPoolKind || null,
      description: newPoolDesc.trim() || null
    });
    newPoolName = ''; newPoolKind = ''; newPoolDesc = '';
    selectedId = p.id;
  }

  // Selection + proxy list
  let selectedId = $state(null);
  let sel = $derived(poolCtx.list.find((p) => p.id === selectedId) ?? poolCtx.list[0] ?? null);
  let proxies = $derived(sel ? (proxyCtx.byPool[sel.id] ?? []) : []);

  $effect(() => {
    if (sel && proxyCtx.byPool[sel.id] === undefined) loadProxies(sel.id);
  });

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

  // Add single proxy
  let addKind = $state('socks5');
  let addHost = $state('');
  let addPort = $state('1080');
  let addSecret = $state('');
  let addSource = $state('');

  async function submitProxy(e) {
    e.preventDefault();
    if (!sel || !addHost.trim() || !addPort) return;
    await addProxy(sel.id, {
      kind: addKind,
      host: addHost.trim(),
      port: addPort,
      secret: addSecret || null,
      source: addSource.trim() || null,
      notes: null
    });
    addHost = ''; addSecret = ''; addSource = '';
  }

  // Bulk import
  let bulkOpen = $state(false);
  let bulkLines = $state('');
  let bulkDefaultKind = $state('socks5');
  let bulkSource = $state('');
  let bulkResult = $state(null);

  async function submitBulk(e) {
    e.preventDefault();
    if (!sel || !bulkLines.trim()) return;
    const lines = bulkLines.split(/\r?\n/).filter((l) => l.trim());
    const r = await bulkAddProxies(sel.id, {
      lines,
      defaultKind: bulkDefaultKind,
      source: bulkSource.trim() || null
    });
    bulkResult = r;
    bulkLines = '';
  }

  // Reveal + state + delete
  async function doReveal(p) {
    try {
      const s = await revealSecret(p.id);
      alert(s ? `Secret for ${p.host}:${p.port}:\n\n${s}` : 'No credential set');
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

  const POOL_COLS = [
    { key: 'name', header: 'Pool', mono: true },
    { key: 'kindHint', header: 'Kind hint', mono: true, width: '110px' },
    { key: 'created', header: 'Created', mono: true, align: 'right', width: '180px' }
  ];

  onMount(loadPools);
</script>

<main>
  <SectionHeader group="System" slug="proxies" title="Proxy pools" />

  <div class="body">
    <div class="left">
      <form class="new" onsubmit={submitPool}>
        <input class="fin" placeholder="New pool name" bind:value={newPoolName} />
        <select class="fin" bind:value={newPoolKind}>
          <option value="">kind hint...</option>
          {#each KINDS as k}<option value={k}>{k}</option>{/each}
        </select>
        <input class="fin" placeholder="Description (optional)" bind:value={newPoolDesc} />
        <Button type="submit" variant="primary" size="sm" disabled={!newPoolName.trim()}>Create pool</Button>
      </form>

      {#if poolCtx.error}
        <p class="err">{poolCtx.error}</p>
      {/if}

      <div class="table-scroll">
        <DataTable
          columns={POOL_COLS}
          rows={poolCtx.list}
          rowKey="id"
          selectedKey={sel?.id}
          onselect={(row) => (selectedId = row.id)}
          stickyHead
        />
      </div>
    </div>

    <div class="right">
      {#if !sel}
        <p class="note">Create or select a pool to manage its proxies.</p>
      {:else}
        <Panel title={sel.name} subtitle={sel.description || sel.kindHint || null}>
          <div class="actions">
            <Button variant="quiet" size="sm" onclick={() => (bulkOpen = !bulkOpen)}>
              {bulkOpen ? 'Hide bulk' : 'Bulk import'}
            </Button>
            <Button variant="danger" size="sm" onclick={removePool}>Delete pool</Button>
          </div>
        </Panel>

        <form class="new" onsubmit={submitProxy}>
          <select class="fin" bind:value={addKind}>
            {#each KINDS as k}<option value={k}>{k}</option>{/each}
          </select>
          <input class="fin" placeholder="host" bind:value={addHost} />
          <input class="fin small" placeholder="port" bind:value={addPort} type="number" min="1" max="65535" />
          <input class="fin" placeholder="user:pass (or MTProxy hex secret)" bind:value={addSecret} />
          <input class="fin small" placeholder="source" bind:value={addSource} />
          <Button type="submit" variant="primary" size="sm" disabled={!addHost.trim()}>Add proxy</Button>
        </form>

        {#if bulkOpen}
          <form class="bulk" onsubmit={submitBulk}>
            <label class="hint">
              Paste lines. Accepted: <code>socks5://host:port</code>,
              <code>socks5://user:pass@host:port</code>,
              <code>http://...</code>, <code>mtproto://host:port?secret=HEX</code>,
              <code>host:port</code>, <code>host:port:user:pass</code>.
            </label>
            <textarea class="fin" rows="8" placeholder="one per line..." bind:value={bulkLines}></textarea>
            <div class="row">
              <select class="fin" bind:value={bulkDefaultKind}>
                {#each KINDS as k}<option value={k}>default kind: {k}</option>{/each}
              </select>
              <input class="fin" placeholder="source tag (e.g. shady-paste-20261112)" bind:value={bulkSource} />
              <Button type="submit" variant="primary" size="sm" disabled={!bulkLines.trim()}>Import</Button>
            </div>
            {#if bulkResult}
              <p class="hint">
                Inserted <b>{bulkResult.inserted}</b>, duplicates <b>{bulkResult.skipped_duplicate}</b>,
                rejected <b>{bulkResult.rejected.length}</b>.
              </p>
              {#if bulkResult.rejected.length}
                <details><summary>rejected lines</summary>
                  <ul>
                    {#each bulkResult.rejected as r}<li><code>{r}</code></li>{/each}
                  </ul>
                </details>
              {/if}
            {/if}
          </form>
        {/if}

        <h3 class="list-head">Proxies <span class="hint">({proxies.length})</span></h3>
        {#if proxyCtx.loading[sel.id]}
          <p class="note">Loading...</p>
        {:else if !proxies.length}
          <p class="note">No proxies in this pool.</p>
        {:else}
          <div class="proxy-list">
            {#each proxies as p (p.id)}
              <div class="row-item state-{p.state}">
                <div class="meta">
                  <span class="kind">{p.kind}</span>
                  <span class="hostport">{p.host}:{p.port}</span>
                  <span class="badge state-{p.state}">{p.state}</span>
                  {#if p.hasSecret}<span class="badge auth">auth</span>{/if}
                  {#if p.source}<span class="src">{p.source}</span>{/if}
                  {#if p.boundIdentityId}<span class="bound">sticky-bound</span>{/if}
                </div>
                {#if p.lastError}<div class="err">{p.lastError}</div>{/if}
                <div class="actions">
                  {#if p.hasSecret}
                    <Button variant="quiet" size="sm" onclick={() => doReveal(p)}>Reveal</Button>
                  {/if}
                  {#each STATES.filter((s) => s !== p.state) as s}
                    <Button variant="quiet" size="sm" onclick={() => flipState(p, s)}>{s}</Button>
                  {/each}
                  <Button variant="danger" size="sm" onclick={() => dropProxy(p)}>Delete</Button>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      {/if}
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: auto; background: var(--black); padding-bottom: 24px; }
  .body { display: grid; grid-template-columns: 420px 1fr; gap: 16px; padding: 16px 20px; align-items: start; }
  @media (max-width: 920px) { .body { grid-template-columns: 1fr; } }
  .left, .right { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .new, .bulk { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); }
  .new { grid-template-columns: 1fr 1fr auto; }
  .bulk .row { display: grid; grid-template-columns: 1fr 1fr auto; gap: 8px; }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin.small { max-width: 110px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .table-scroll { max-height: 68vh; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius); }
  .note { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); padding: 8px 2px; }
  .err { color: var(--red-text); font-family: var(--font-mono); font-size: var(--fs-12); padding: 4px 2px; }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .hint code { background: var(--panel); padding: 1px 5px; border-radius: 4px; }
  .actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .list-head { margin: 8px 0 0; font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .proxy-list { display: flex; flex-direction: column; gap: 6px; }
  .row-item { display: grid; grid-template-columns: 1fr auto; gap: 6px; align-items: center; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); }
  .meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-family: var(--font-mono); font-size: var(--fs-12); }
  .kind { background: var(--surface); padding: 1px 6px; border-radius: 4px; text-transform: uppercase; font-size: var(--fs-10); color: var(--text-secondary); }
  .hostport { color: var(--text-body); }
  .badge { font-size: var(--fs-10); padding: 1px 6px; border-radius: 4px; text-transform: uppercase; }
  .badge.state-active { background: var(--accent-bg); color: var(--accent-text); }
  .badge.state-cooling { background: var(--warn-bg, #4a3a00); color: var(--warn-text, #ffd37a); }
  .badge.state-burned { background: var(--red-bg); color: var(--red-text); }
  .badge.state-disabled { background: var(--surface); color: var(--text-faint); }
  .badge.auth { background: var(--surface); color: var(--text-faint); }
  .src { font-size: var(--fs-10); color: var(--text-faint); }
  .bound { font-size: var(--fs-10); color: var(--accent-text); }
</style>
