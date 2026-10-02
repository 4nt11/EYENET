<script>
  import { onMount } from 'svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { identityCtx, identityView, identityTone, loadIdentities, loadIdentityDetail, identityAction, deleteIdentity, freezeAll, replaceSession } from '$lib/identity.svelte.js';
  import { sourceCtx, loadSources } from '$lib/source.svelte.js';
  import { curlToNetscape, hostFromUrl } from '$lib/curl-cookies.js';

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
          ...(identityView.delayMin != null
            ? [{
                label: 'Profile',
                value: `${identityView.evasion ?? 'custom'} · ${identityView.delayMin}-${identityView.delayMax}s/req`
                  + (identityView.discoveryDepth != null
                      ? ` · ${identityView.discoveryDepth === 0 ? 'index only' : `depth ${identityView.discoveryDepth}`}`
                      : ''),
                tone: 'accent'
              }]
            : []),
          ...(identityView.notes ? [{ label: 'Notes', value: identityView.notes, mono: false }] : [])
        ]
      : []
  );

  let reason = $state('');
  // Credential rotation (fresh cookies / .session after a logout) — only the
  // session changes. Kind-aware: forum = cookie paste, telegram = .session upload
  // (or QR re-login). Resolved from the identity's source.
  let cookieInput = $state('');
  let sessionFile = $state(null);
  let showReplace = $state(false);
  const sourceOf = $derived(sourceCtx.list.find((s) => s.id === sel?.sourceId) ?? null);
  const sourceKind = $derived(sourceOf?.platform ?? '');
  const forumHost = $derived(hostFromUrl(sourceOf?.forumBaseUrl ?? ''));

  $effect(() => {
    if (sel) loadIdentityDetail(sel.id);
  });

  // Reset the replace control whenever the selected identity changes.
  $effect(() => {
    void sel?.id;
    showReplace = false;
    cookieInput = '';
    sessionFile = null;
  });

  onMount(() => {
    loadIdentities();
    loadSources(); // resolve the source kind + forum host for the replace control
  });

  async function doReplaceSession() {
    if (!sel) return;
    let file;
    if (sourceKind === 'telegram') {
      if (!sessionFile) return;
      file = sessionFile; // a File with its own .session name
    } else {
      if (!cookieInput.trim()) return;
      let text = cookieInput.trim();
      // Already a Netscape jar (tab-delimited rows)? send as-is. Otherwise treat
      // the input as a DevTools "Copy as cURL" / Cookie header and extract, scoped
      // to the source's forum host.
      if (!text.includes('\t')) {
        try {
          text = curlToNetscape(cookieInput, forumHost).text;
        } catch (e) {
          identityView.submitMsg = `✗ ${e.message ?? e}`;
          return;
        }
      }
      file = new File([text], 'cookies.txt', { type: 'text/plain' });
    }
    const ok = await replaceSession(sel.id, file);
    if (ok) {
      cookieInput = '';
      sessionFile = null;
      showReplace = false;
    }
  }

  async function act(action) {
    if (!reason.trim() || !sel) return;
    await identityAction(sel.id, action, reason.trim());
    reason = '';
  }

  function doFreezeAll() {
    const r = window.prompt('Reason for freezing ALL identities:');
    if (r && r.trim()) freezeAll(r.trim());
  }

  async function removeIdentity() {
    if (!sel) return;
    if (!confirm(`Delete identity "${sel.name}"? Removes it entirely — use Burn to retire a compromised one.`)) return;
    const gone = await deleteIdentity(sel.id);
    if (gone) selectedId = null;
  }
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">System</span><span class="sep">/</span><span class="slug">identities</span></div>
      <h1>Identity pool</h1>
    </div>
    <div class="head-actions">
      <a class="provision-link" href="/identities/provision">Provision identity</a>
      <Button variant="destructive" size="sm" disabled={identityView.submitting || !identityCtx.list.length} onclick={doFreezeAll}>Freeze all</Button>
    </div>
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
            {#if sel.state === 'burned'}<span class="terminal">Burned · terminal lifecycle.</span>{/if}
          </div>
          <div class="session-row">
            <div class="actions-label">Credential</div>
            {#if !showReplace}
              <Button variant="ghost" size="sm" disabled={identityView.submitting} onclick={() => (showReplace = true)}>Replace credential</Button>
              <span class="hint">Swap the session after a logout — fresh cookies (forum) or a new .session / QR re-login (Telegram). Nothing else changes.</span>
            {:else if sourceKind === 'telegram'}
              <input class="field file" type="file" accept=".session" onchange={(e) => (sessionFile = e.currentTarget.files?.[0] ?? null)} />
              <div class="actions-row">
                <Button variant="primary" size="sm" disabled={identityView.submitting || !sessionFile} onclick={doReplaceSession}>Replace .session</Button>
                <a class="relogin-link" href={`/identities/provision/qr?identity=${sel.id}`}>…or re-login via QR</a>
                <Button variant="ghost" size="sm" disabled={identityView.submitting} onclick={() => { showReplace = false; sessionFile = null; }}>Cancel</Button>
              </div>
              <span class="hint">Upload a fresh Telegram .session, or re-login live via QR (reuses this identity's api credentials).</span>
            {:else}
              <textarea class="field mono" rows="3" bind:value={cookieInput} placeholder={'Paste DevTools "Copy as cURL", a Cookie header, or a Netscape cookies.txt'}></textarea>
              <div class="actions-row">
                <Button variant="primary" size="sm" disabled={identityView.submitting || !cookieInput.trim()} onclick={doReplaceSession}>Replace</Button>
                <Button variant="ghost" size="sm" disabled={identityView.submitting} onclick={() => { showReplace = false; cookieInput = ''; }}>Cancel</Button>
              </div>
              <span class="hint">{forumHost ? `cURL cookies will be scoped to ${forumHost}.` : 'Netscape cookies.txt or a Cookie header (no forum host known for cURL scoping).'}</span>
            {/if}
          </div>
          <div class="danger-row">
            <Button variant="destructive" size="sm" disabled={identityView.submitting} onclick={removeIdentity}>Delete identity</Button>
            <span class="hint">Removes the row (only if no collector binds it). Burn to retire a compromised one.</span>
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
  .head-actions { display: flex; align-items: center; gap: 10px; }
  .provision-link { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-secondary); text-decoration: none; padding: 0 4px; }
  .provision-link:hover { color: var(--accent); }
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
  .field.mono { font-family: var(--font-mono); font-size: var(--fs-12); resize: vertical; }
  .field.file { padding: 6px 8px; font-family: var(--font-sans); font-size: var(--fs-12); }
  .relogin-link { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-secondary); text-decoration: none; }
  .relogin-link:hover { color: var(--accent); }
  .session-row { display: flex; flex-direction: column; gap: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
  .danger-row { display: flex; align-items: center; gap: 10px; padding-top: 8px; border-top: 1px solid var(--border); }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .submitmsg { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
