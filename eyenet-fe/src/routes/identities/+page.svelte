<script>
  import { onMount } from 'svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { identityCtx, identityView, identityTone, loadIdentities, loadIdentityDetail, identityAction, deleteIdentity, freezeAll, replaceSession, saveIdentityConfig } from '$lib/identity.svelte.js';
  import { sourceCtx, loadSources } from '$lib/source.svelte.js';
  import { curlToNetscape, extractCookieString, hostFromUrl } from '$lib/curl-cookies.js';

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

  // Live classification of the pasted cookie blob, so the operator sees it parsed
  // BEFORE pressing Replace: Netscape jar vs cURL/Cookie-header, and the count.
  const cookiePreview = $derived.by(() => {
    const t = cookieInput.trim();
    if (!t) return null;
    if (t.includes('\t')) {
      const n = t.split('\n').filter((l) => l.includes('\t') && !l.trimStart().startsWith('#')).length;
      return n ? { kind: 'Netscape jar', n } : { kind: 'unparsed', n: 0 };
    }
    const cs = extractCookieString(cookieInput);
    const n = cs ? cs.split(';').filter((p) => p.includes('=')).length : 0;
    return n ? { kind: 'cURL / Cookie header', n } : { kind: 'unparsed', n: 0 };
  });
  // Set when we auto-converted a pasted cURL into the Netscape jar now in the box.
  let converted = $state(false);

  // Auto-convert a pasted cURL / Cookie header into a Netscape jar IN PLACE, so the
  // box shows exactly what gets sent. Needs the forum host to scope; already-Netscape
  // (has tabs) and un-parseable input are left untouched.
  function onCookieInput(e) {
    const v = e.currentTarget.value;
    if (v.trim() && !v.includes('\t') && forumHost) {
      try {
        cookieInput = curlToNetscape(v, forumHost).text;
        converted = true;
        return;
      } catch {
        /* leave as typed; the preview line explains */
      }
    }
    cookieInput = v;
    converted = false;
  }

  $effect(() => {
    if (sel) loadIdentityDetail(sel.id);
  });

  // Reset the replace control whenever the selected identity changes.
  $effect(() => {
    void sel?.id;
    showReplace = false;
    cookieInput = '';
    sessionFile = null;
    converted = false;
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
    const note =
      sourceKind === 'telegram'
        ? sessionFile?.name
        : cookiePreview?.n
          ? `${cookiePreview.n} cookie${cookiePreview.n === 1 ? '' : 's'}`
          : '';
    const ok = await replaceSession(sel.id, file, { note });
    if (ok) {
      cookieInput = '';
      sessionFile = null;
      showReplace = false;
      converted = false;
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

  // --- collector config editor ---
  // Hover help per field (native title tooltip), so the knobs are self-explaining.
  const HELP = {
    forum_base_url: 'The forum root URL (onion or clearnet). Everything the collector crawls is resolved against this.',
    forum_thread_urls: 'Specific thread URLs to monitor directly, one per line. Leave empty to rely on category discovery.',
    forum_engine: 'The forum software — selects the HTML parser (mybb, xenforo, …). A wrong engine silently parses nothing.',
    forum_evasion_level: 'Named pacing preset: ghost (slowest/stealthiest) → lurker → regular → brisk → smash (fastest). Picking one fills in the delay + discovery-depth values below; "custom" keeps your manual numbers.',
    forum_delay_min: 'Minimum wait between requests (seconds). Each fetch waits a RANDOM time between min and max — higher is stealthier but slower.',
    forum_delay_max: 'Maximum wait between requests (seconds). Each fetch waits a random time between min and max.',
    forum_discovery_depth: 'How many subforum levels to descend when enumerating categories. 0 = only the top-level categories on the index.',
    forum_discovery_interval: 'How often (seconds) to re-enumerate the category thread-lists to find new threads. Higher = quieter / less load.',
    forum_max_category_pages: 'Cap on how many category listing pages are crawled per sweep. 0 = no cap (all pages).',
    forum_max_thread_pages: 'How many pages deep to read within a thread on a sweep. 0 = all pages; 1 = first page only.',
    forum_steady_pages: 'In steady-state polling (after the first backfill), how many recent pages of each thread to re-check for new posts.',
    forum_tls_impersonate: 'curl-cffi TLS fingerprint (JA3/JA4) used on a clearnet WAF board. MUST match the User-Agent and the browser that minted the cookie jar. "none" uses plain httpx (fine over Tor, where TLS is wrapped).',
    forum_user_agent: 'The exact User-Agent of the browser that exported the cookie jar. Must stay coherent with the TLS impersonate target — a UA flip mid-session is itself a ban signal.',
    forum_enable_waf_bypass: 'Route requests through FlareSolverr (a real headless browser) to clear a Cloudflare JS challenge / Anubis proof-of-work. Off by default.',
    monitor_groups: 'Telegram groups/channels to collect, one per line — a @username or a numeric -100… channel id.'
  };
  const EVASION_LEVELS = ['', 'ghost', 'lurker', 'regular', 'brisk', 'smash'];
  // curl-cffi targets (FORUM_TLS_IMPERSONATE_TARGETS) + '' = none (httpx/Tor path).
  const IMPERSONATE_TARGETS = ['', 'firefox147', 'firefox135', 'chrome131'];

  let showConfig = $state(false);
  let restartOnSave = $state(false);
  let cfg = $state(null);

  const splitLines = (s) => (s ?? '').split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
  const arrEq = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

  // Keep numeric fields numeric: strip anything non-numeric on input, and force the
  // cleaned value back onto the DOM so a stray char can't stick when the model is
  // unchanged (type "5" then "a" both sanitize to "5"). `decimal` allows one dot.
  function sanitizeNum(raw, decimal) {
    const s = String(raw ?? '');
    return decimal ? s.replace(/[^\d.]/g, '').replace(/(\.\d*)\./g, '$1') : s.replace(/\D/g, '');
  }
  function onNum(e, key, decimal = false) {
    const clean = sanitizeNum(e.currentTarget.value, decimal);
    e.currentTarget.value = clean;
    cfg[key] = clean;
  }

  function seedCfg(r) {
    return {
      forum_base_url: r.forum_base_url ?? '',
      forum_thread_urls: (r.forum_thread_urls ?? []).join('\n'),
      forum_engine: r.forum_engine ?? '',
      forum_user_agent: r.forum_user_agent ?? '',
      forum_evasion_level: r.forum_evasion_level ?? '',
      forum_tls_impersonate: r.forum_tls_impersonate ?? '',
      forum_enable_waf_bypass: !!r.forum_enable_waf_bypass,
      forum_delay_min: r.forum_delay_min ?? '',
      forum_delay_max: r.forum_delay_max ?? '',
      forum_discovery_interval: r.forum_discovery_interval ?? '',
      forum_max_category_pages: r.forum_max_category_pages ?? '',
      forum_max_thread_pages: r.forum_max_thread_pages ?? '',
      forum_steady_pages: r.forum_steady_pages ?? '',
      forum_discovery_depth: r.forum_discovery_depth ?? '',
      monitor_groups: (r.monitor_groups ?? []).join('\n')
    };
  }

  // Re-seed the draft whenever the loaded detail changes (select / after save).
  $effect(() => {
    if (identityView.raw) cfg = seedCfg(identityView.raw);
  });

  function buildUpdates() {
    const r = identityView.raw;
    const u = {};
    if (!r || !cfg) return u;
    if (sourceKind === 'telegram') {
      const mg = splitLines(cfg.monitor_groups);
      if (!arrEq(mg, r.monitor_groups ?? [])) u.monitor_groups = mg;
      return u;
    }
    const setStr = (k) => { const v = (cfg[k] ?? '').trim(); if (v !== (r[k] ?? '')) u[k] = v; };
    ['forum_base_url', 'forum_engine', 'forum_user_agent', 'forum_evasion_level', 'forum_tls_impersonate'].forEach(setStr);
    const tu = splitLines(cfg.forum_thread_urls);
    if (!arrEq(tu, r.forum_thread_urls ?? [])) u.forum_thread_urls = tu;
    if (cfg.forum_enable_waf_bypass !== !!r.forum_enable_waf_bypass) u.forum_enable_waf_bypass = cfg.forum_enable_waf_bypass;
    // Only send a numeric if the operator actually changed it — so picking a new evasion
    // level (which the backend expands) isn't clobbered by stale delay fields in the box.
    const setNum = (k) => { const v = cfg[k]; if (v === '' || v === null) return; const n = Number(v); if (n !== r[k]) u[k] = n; };
    ['forum_delay_min', 'forum_delay_max', 'forum_discovery_interval', 'forum_max_category_pages', 'forum_max_thread_pages', 'forum_steady_pages', 'forum_discovery_depth'].forEach(setNum);
    return u;
  }

  const pendingUpdates = $derived(buildUpdates());
  const dirty = $derived(Object.keys(pendingUpdates).length > 0);

  async function saveConfig() {
    if (!sel || !dirty) return;
    await saveIdentityConfig(sel.id, pendingUpdates, { restart: restartOnSave });
    restartOnSave = false;
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
              <textarea class="field mono" rows="4" value={cookieInput} oninput={onCookieInput} placeholder={'Paste DevTools "Copy as cURL", a Cookie header, or a Netscape cookies.txt'}></textarea>
              {#if cookiePreview}
                {#if cookiePreview.n > 0}
                  <span class="preview ok">{converted ? `✓ cURL detected → auto-converted to a Netscape jar · ${cookiePreview.n} cookie${cookiePreview.n === 1 ? '' : 's'} → ${forumHost}` : `✓ ${cookiePreview.kind} detected · ${cookiePreview.n} cookie${cookiePreview.n === 1 ? '' : 's'}`}</span>
                {:else}
                  <span class="preview err">✗ couldn't read cookies — paste a Copy-as-cURL, a Cookie header, or a Netscape cookies.txt</span>
                {/if}
              {/if}
              <div class="actions-row">
                <Button variant="primary" size="sm" disabled={identityView.submitting || !cookiePreview || cookiePreview.n === 0} onclick={doReplaceSession}>Replace</Button>
                <Button variant="ghost" size="sm" disabled={identityView.submitting} onclick={() => { showReplace = false; cookieInput = ''; converted = false; }}>Cancel</Button>
              </div>
              <span class="hint">cURL is auto-converted to a Netscape jar{forumHost ? ` scoped to ${forumHost}` : ''}. Already-Netscape text is sent as-is.</span>
            {/if}
          </div>
          <div class="config-row">
            <div class="actions-label">Collector config</div>
            {#if !showConfig}
              <Button variant="ghost" size="sm" onclick={() => (showConfig = true)}>Edit config</Button>
              <span class="hint">Pacing, evasion, engine, fingerprint. Read at collector boot — editing it does not take effect until the collector restarts.</span>
            {:else if cfg}
              {#if sourceKind === 'telegram'}
                <label class="cfg-f" title={HELP.monitor_groups}>Monitored groups (one per line) <span class="q">?</span>
                  <textarea class="field mono" rows="4" bind:value={cfg.monitor_groups} placeholder="@channel or -100… id"></textarea>
                </label>
              {:else}
                <div class="cfg-grid">
                  <label class="cfg-f wide" title={HELP.forum_base_url}>Base URL <span class="q">?</span><input class="field" type="text" bind:value={cfg.forum_base_url} /></label>
                  <label class="cfg-f wide" title={HELP.forum_thread_urls}>Thread URLs (one per line) <span class="q">?</span>
                    <textarea class="field mono" rows="3" bind:value={cfg.forum_thread_urls}></textarea>
                  </label>
                  <label class="cfg-f" title={HELP.forum_engine}>Engine <span class="q">?</span><input class="field" type="text" bind:value={cfg.forum_engine} placeholder="mybb" /></label>
                  <label class="cfg-f" title={HELP.forum_evasion_level}>Evasion level <span class="q">?</span>
                    <select class="field" bind:value={cfg.forum_evasion_level}>
                      {#each EVASION_LEVELS as lvl}<option value={lvl}>{lvl || '— custom —'}</option>{/each}
                    </select>
                  </label>
                  <label class="cfg-f" title={HELP.forum_delay_min}>Delay min (s) <span class="q">?</span><input class="field" type="text" inputmode="decimal" value={cfg.forum_delay_min} oninput={(e) => onNum(e, 'forum_delay_min', true)} spellcheck="false" autocomplete="off" /></label>
                  <label class="cfg-f" title={HELP.forum_delay_max}>Delay max (s) <span class="q">?</span><input class="field" type="text" inputmode="decimal" value={cfg.forum_delay_max} oninput={(e) => onNum(e, 'forum_delay_max', true)} spellcheck="false" autocomplete="off" /></label>
                  <label class="cfg-f" title={HELP.forum_discovery_depth}>Discovery depth <span class="q">?</span><input class="field" type="text" inputmode="numeric" value={cfg.forum_discovery_depth} oninput={(e) => onNum(e, 'forum_discovery_depth')} spellcheck="false" autocomplete="off" /></label>
                  <label class="cfg-f" title={HELP.forum_discovery_interval}>Discovery interval (s) <span class="q">?</span><input class="field" type="text" inputmode="numeric" value={cfg.forum_discovery_interval} oninput={(e) => onNum(e, 'forum_discovery_interval')} spellcheck="false" autocomplete="off" /></label>
                  <label class="cfg-f" title={HELP.forum_max_category_pages}>Max category pages <span class="q">?</span><input class="field" type="text" inputmode="numeric" value={cfg.forum_max_category_pages} oninput={(e) => onNum(e, 'forum_max_category_pages')} spellcheck="false" autocomplete="off" /></label>
                  <label class="cfg-f" title={HELP.forum_max_thread_pages}>Max thread pages <span class="q">?</span><input class="field" type="text" inputmode="numeric" value={cfg.forum_max_thread_pages} oninput={(e) => onNum(e, 'forum_max_thread_pages')} spellcheck="false" autocomplete="off" /></label>
                  <label class="cfg-f" title={HELP.forum_steady_pages}>Steady pages <span class="q">?</span><input class="field" type="text" inputmode="numeric" value={cfg.forum_steady_pages} oninput={(e) => onNum(e, 'forum_steady_pages')} spellcheck="false" autocomplete="off" /></label>
                  <label class="cfg-f" title={HELP.forum_tls_impersonate}>TLS impersonate <span class="q">?</span>
                    <select class="field" bind:value={cfg.forum_tls_impersonate}>
                      {#each IMPERSONATE_TARGETS as t}<option value={t}>{t || '— none (Tor/httpx) —'}</option>{/each}
                    </select>
                  </label>
                  <label class="cfg-f wide" title={HELP.forum_user_agent}>User-Agent <span class="q">?</span><input class="field" type="text" bind:value={cfg.forum_user_agent} /></label>
                  <label class="cfg-f check" title={HELP.forum_enable_waf_bypass}><input type="checkbox" bind:checked={cfg.forum_enable_waf_bypass} /> Enable WAF bypass (FlareSolverr) <span class="q">?</span></label>
                </div>
                <p class="warn-note">⚠ Fingerprint coherence: User-Agent, TLS impersonate, and the browser that minted the cookie jar must ALL be the same Firefox. A mismatch is more detectable than no impersonation.</p>
              {/if}
              <label class="cfg-f check restart">
                <input type="checkbox" bind:checked={restartOnSave} disabled={!identityView.collectorId} />
                Restart the collector on save to apply now
                {#if identityView.collectorId}
                  <span class="hint inline">(its session will briefly drop{identityView.collectorState ? ` · now ${identityView.collectorState}` : ''})</span>
                {:else}
                  <span class="hint inline">(no collector bound — save only; it applies next time one runs)</span>
                {/if}
              </label>
              {#if !restartOnSave}<span class="hint">Unchecked: changes are saved but the running collector keeps the OLD config until you restart it.</span>{/if}
              <div class="actions-row">
                <Button variant="primary" size="sm" disabled={identityView.submitting || !dirty} onclick={saveConfig}>{restartOnSave ? 'Save & restart' : 'Save config'}</Button>
                <Button variant="ghost" size="sm" disabled={identityView.submitting} onclick={() => { showConfig = false; restartOnSave = false; cfg = seedCfg(identityView.raw); }}>Cancel</Button>
                {#if dirty}<span class="hint">{Object.keys(pendingUpdates).length} field(s) changed</span>{/if}
              </div>
            {/if}
          </div>
          <div class="danger-row">
            <Button variant="destructive" size="sm" disabled={identityView.submitting} onclick={removeIdentity}>Delete identity</Button>
            <span class="hint">Removes the row (only if no collector binds it). Burn to retire a compromised one.</span>
          </div>
          {#if identityView.submitMsg}<p class="submitmsg" class:ok={identityView.submitTone === 'ok'} class:err={identityView.submitTone === 'err'} class:warn={identityView.submitTone === 'warn'}>{identityView.submitMsg}</p>{/if}
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
  .submitmsg.ok { color: var(--accent-text); }
  .submitmsg.err { color: var(--red-text); }
  .submitmsg.warn { color: var(--warn-text, #d8a657); }

  .config-row { display: flex; flex-direction: column; gap: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
  .cfg-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .cfg-f { display: flex; flex-direction: column; gap: 4px; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .cfg-f.wide { grid-column: 1 / -1; }
  .q { display: inline-flex; align-items: center; justify-content: center; width: 13px; height: 13px; border: 1px solid var(--border-strong); border-radius: 50%; font-size: 9px; color: var(--text-faint); cursor: help; vertical-align: middle; }
  .cfg-f:hover .q { border-color: var(--accent); color: var(--accent-text); }
  .cfg-f.check { flex-direction: row; align-items: center; gap: 8px; color: var(--text-body); font-size: var(--fs-12); }
  .cfg-f.check.restart { padding-top: 6px; border-top: 1px solid var(--border); margin-top: 4px; }
  .cfg-f select.field { font-family: var(--font-mono); font-size: var(--fs-12); }
  .hint.inline { display: inline; }
  .warn-note { margin: 2px 0 0; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--warn-text, #d8a657); line-height: var(--lh-normal); }
  .preview { margin: -2px 0 0; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .preview.ok { color: var(--accent-text); }
  .preview.err { color: var(--red-text); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
