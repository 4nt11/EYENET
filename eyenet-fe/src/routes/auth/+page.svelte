<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Button from '$lib/components/Button.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import { SIGNING_KEYS, KEY_COLUMNS } from '$lib/data.js';
  import { auth, logout } from '$lib/auth.svelte.js';
  import {
    tokenCtx,
    mintResult,
    loadTokens,
    mintToken,
    revokeToken,
    clearMintResult
  } from '$lib/token.svelte.js';

  const COLUMNS = [
    { key: 'prefix', header: 'Token', mono: true, width: '230px' },
    { key: 'label', header: 'Label', mono: true, width: '150px' },
    { key: 'scopes', header: 'Scopes', mono: true },
    { key: 'last_used', header: 'Last used', mono: true, align: 'right', width: '150px' },
    { key: 'status', header: 'Status', mono: true, align: 'right', width: '84px' }
  ];

  // Scopes the operator holds — the ceiling for a new PAT (server re-enforces).
  const heldScopes = $derived([...(auth.user?.scopes ?? [])].sort());

  // Group `verb:resource` scopes by RESOURCE, with the held verbs as toggles —
  // a flat grid of `read:audit` etc. is unreadable at 30+ scopes.
  const VERB_ORDER = ['read', 'write', 'stream', 'admin'];
  const scopeTree = $derived.by(() => {
    const byRes = new Map();
    for (const s of heldScopes) {
      const i = s.indexOf(':');
      if (i < 0) continue;
      const res = s.slice(i + 1);
      if (!byRes.has(res)) byRes.set(res, new Set());
      byRes.get(res).add(s.slice(0, i));
    }
    return [...byRes.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([res, verbs]) => ({
        res,
        verbs: [...verbs].sort((a, b) => VERB_ORDER.indexOf(a) - VERB_ORDER.indexOf(b))
      }));
  });

  let showMint = $state(false);
  let mintName = $state('');
  let mintScopes = $state(new Set());
  let mintExpiry = $state(''); // yyyy-mm-dd, optional
  let selectedId = $state(null);
  const sel = $derived(tokenCtx.list.find((t) => t.id === selectedId) ?? null);
  const canMint = $derived(mintName.trim().length > 0 && mintScopes.size > 0 && !tokenCtx.busy);

  onMount(loadTokens);

  function openMint() {
    mintName = '';
    mintScopes = new Set();
    mintExpiry = '';
    tokenCtx.error_msg = null;
    showMint = true;
  }

  function toggleScope(s) {
    const next = new Set(mintScopes);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    mintScopes = next;
  }

  async function doMint() {
    if (!canMint) return;
    const expiresAt = mintExpiry ? new Date(mintExpiry + 'T00:00:00Z').toISOString() : null;
    const ok = await mintToken({ name: mintName.trim(), scopes: [...mintScopes], expiresAt });
    if (ok) showMint = false; // the one-time secret now shows via mintResult
  }

  async function doRevoke() {
    if (!sel) return;
    if (!confirm(`Revoke token "${sel.label}" (${sel.prefix})? This cannot be undone.`)) return;
    const ok = await revokeToken(sel.id);
    if (ok) selectedId = null;
  }

  async function copySecret() {
    try {
      await navigator.clipboard.writeText(mintResult.secret);
    } catch {
      /* clipboard blocked — the operator can select the text manually */
    }
  }
</script>

<main>
  <SectionHeader group="System" slug="auth" title="Auth & tokens" />

  <div class="body">
    <!-- Session -->
    <Panel title="Session">
      {#snippet action()}<Button variant="ghost" size="sm" onclick={logout}>Sign out</Button>{/snippet}
      <div class="session">
        <div class="srow"><span class="k">Operator</span><span class="v accent">{auth.user?.username ?? '—'}</span></div>
        <div class="srow"><span class="k">Role</span><span class="v">{auth.user?.role ?? '—'}</span></div>
        <div class="srow top"><span class="k">Scopes</span>
          <span class="scopes">{#each heldScopes as s}<span class="scope">{s}</span>{/each}</span>
        </div>
      </div>
    </Panel>

    <!-- One-time secret, surfaced right after mint -->
    {#if mintResult.secret}
      <Panel title="New token — copy it now">
        <div class="secret-box">
          <p class="secret-warn">✓ Minted <strong>{mintResult.label}</strong>. This is the only time the full token is shown — copy it into your scraper now.</p>
          <div class="secret-row">
            <code class="secret">{mintResult.secret}</code>
            <Button variant="primary" size="sm" onclick={copySecret}>Copy</Button>
            <Button variant="ghost" size="sm" onclick={clearMintResult}>Done</Button>
          </div>
        </div>
      </Panel>
    {/if}

    <!-- Personal access tokens -->
    <Panel title="Personal access tokens">
      {#snippet action()}<Button variant="primary" size="sm" onclick={openMint}>Mint token</Button>{/snippet}

      {#if showMint}
        <div class="mint">
          <label class="fld"><span class="flabel">Label</span>
            <input class="fin" type="text" bind:value={mintName} placeholder="prometheus-scrape" /></label>
          <div class="fld"><span class="flabel">Scopes — pick per resource; a token carries only scopes you hold</span>
            <div class="scopesecs">
              {#each scopeTree as { res, verbs }}
                <div class="scard">
                  <span class="scard-res">{res.replaceAll('_', ' ')}</span>
                  <div class="verbs">
                    {#each verbs as v}
                      {@const full = `${v}:${res}`}
                      <button type="button" class="verbchip" class:on={mintScopes.has(full)}
                        onclick={() => toggleScope(full)}>{v}</button>
                    {/each}
                  </div>
                </div>
              {/each}
            </div>
            {#if mintScopes.size}<span class="picked">{mintScopes.size} selected · {[...mintScopes].sort().join('  ')}</span>{/if}
          </div>
          <label class="fld"><span class="flabel">Expiry (optional)</span>
            <input class="fin" type="date" bind:value={mintExpiry} /></label>
          {#if tokenCtx.error_msg}<p class="err">{tokenCtx.error_msg}</p>{/if}
          <div class="mint-actions">
            <Button variant="primary" size="sm" disabled={!canMint} onclick={doMint}>Mint</Button>
            <Button variant="ghost" size="sm" disabled={tokenCtx.busy} onclick={() => (showMint = false)}>Cancel</Button>
          </div>
        </div>
      {/if}

      {#if tokenCtx.list.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={tokenCtx.list}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
        {#if sel}
          <div class="revoke-row">
            <span class="sel-note">Selected: <code>{sel.prefix}</code> · {sel.label}</span>
            <Button variant="destructive" size="sm" disabled={tokenCtx.busy} onclick={doRevoke}>Revoke token</Button>
          </div>
        {/if}
      {:else}
        <p class="note">{#if !tokenCtx.loaded}Loading…{:else if tokenCtx.error}Could not load tokens: {tokenCtx.error}{:else}No personal access tokens yet. Mint one for a scraper or CI consumer.{/if}</p>
      {/if}
    </Panel>

    <!-- Signing keys (display only; registration is a separate flow) -->
    <Panel title="Signing keys">
      {#snippet action()}<Button variant="ghost" size="sm">Register key</Button>{/snippet}
      <DataTable rowKey="id" columns={KEY_COLUMNS} rows={SIGNING_KEYS} />
    </Panel>

    <p class="note">Stream tokens are short-lived and minted on demand from an active session; they are not
      listed here. MFA enrollment and recovery are managed under Session.</p>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .body > :global(*) { margin-bottom: 16px; }

  .session { padding: 4px 0; }
  .srow { display: grid; grid-template-columns: 120px 1fr; gap: 12px; align-items: baseline; padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .srow.top { align-items: start; }
  .srow:last-child { border-bottom: none; }
  .k { font-family: var(--font-sans); font-size: var(--fs-12); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .v { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .v.accent { color: var(--accent-text); }
  .scopes { display: flex; flex-wrap: wrap; gap: 6px; }
  .scope { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 2px 7px; }

  .secret-box { display: flex; flex-direction: column; gap: 10px; padding: 4px 2px; }
  .secret-warn { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--accent-text); }
  .secret-row { display: flex; align-items: center; gap: 10px; }
  .secret { flex: 1; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 8px 10px; overflow-x: auto; white-space: nowrap; }

  .mint { display: flex; flex-direction: column; gap: 12px; padding: 4px 2px 14px; border-bottom: 1px solid var(--border); margin-bottom: 12px; }
  .fld { display: flex; flex-direction: column; gap: 6px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; max-width: 420px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .scopesecs { display: grid; grid-template-columns: repeat(auto-fill, minmax(176px, 1fr)); gap: 8px; }
  .scard { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 9px 11px; display: flex; flex-direction: column; gap: 8px; transition: border-color 0.12s; }
  .scard:has(.verbchip.on) { border-color: var(--accent); }
  .scard-res { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .verbs { display: flex; flex-wrap: wrap; gap: 5px; }
  .verbchip { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-secondary); background: var(--black); border: 1px solid var(--border-strong); border-radius: 999px; padding: 2px 11px; cursor: pointer; transition: all 0.12s; }
  .verbchip:hover { border-color: var(--accent); color: var(--text-body); }
  .verbchip.on { color: #fff; background: var(--accent); border-color: var(--accent); }
  .picked { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); word-break: break-word; }
  .mint-actions, .revoke-row { display: flex; align-items: center; gap: 10px; }
  .revoke-row { padding-top: 10px; }
  .sel-note { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .sel-note code { font-family: var(--font-mono); color: var(--text-secondary); }
  .err { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text); }

  .note { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); max-width: 80ch; }
</style>
