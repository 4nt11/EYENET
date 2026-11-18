<script>
  // Per-victim artifact browser + drawer. Card grid on the left; clicking a
  // card slides in the drawer with 5 tabs (Overview, Files, Credentials,
  // System, Audit) and a right-rail SELECTED panel for the file preview /
  // extracted indicators. Backend contract: eyenet.api.v1.stealer.
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import Button from '$lib/components/Button.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import {
    listCtx,
    loadArtifacts,
    drawerCtx,
    openDrawer,
    closeDrawer,
    loadRecords,
    pickFile,
  } from '$lib/stealerArtifacts.svelte.js';

  const shortSha = (s) => (s ? s.slice(0, 8) : '');
  const fmt = (n) => (n ?? 0).toLocaleString();
  // Human-readable byte formatter: 240 B, 51.5 KB, 3.8 MB, 1.2 GB.
  const fmtBytes = (n) => {
    const b = Number(n ?? 0);
    if (!Number.isFinite(b) || b <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.min(units.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
    const v = b / 1024 ** i;
    return `${i === 0 ? v : v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
  };

  // Family tone: corporate markers + wallet presence drive the border tone.
  const cardTone = (c) => {
    if (c.has_corporate_marker) return 'critical';
    if (c.has_wallet) return 'high';
    return 'neutral';
  };

  // Tabs definition. Audit is a stub for now (no backend endpoint yet).
  const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'files', label: 'Files' },
    { id: 'credentials', label: 'Credentials' },
    { id: 'system', label: 'System' },
    { id: 'audit', label: 'Audit' },
  ];

  const pickTab = (id) => {
    drawerCtx.tab = id;
    // Lazy-load records when Credentials or System tab opens.
    if ((id === 'credentials' || id === 'system') && drawerCtx.records.length === 0) {
      loadRecords({ page: 1 });
    }
  };

  // Credentials tab: records filtered to credential-emitting rules. Different
  // rules emit different field names (passwords_block_title: soft/host/login,
  // passwords_block_divider: url/username, credentials_windows: target/user,
  // etc), so the row renderer coalesces across the known key aliases.
  const CRED_RULES = /^(passwords_|credentials_|firefox_logins)/;
  const firstField = (fields, keys) => {
    for (const k of keys) if (fields?.[k]) return fields[k];
    return '';
  };
  const credUrl = (f) => firstField(f, ['url', 'host', 'target']);
  const credUser = (f) => firstField(f, ['login', 'username', 'user']);
  const credPw = (f) => firstField(f, ['password']);
  const credBrowser = (f) => firstField(f, ['browser', 'soft', 'profile']);
  const creds = $derived(
    drawerCtx.records.filter((r) => CRED_RULES.test(r.rule_id ?? '')),
  );
  // Dedupe files by filename until the pipeline stops writing the ephemeral
  // extraction root into rel_path (multiple reindex passes produce distinct
  // rel_paths for the same logical file, so FINAL on file_audit can't
  // collapse them). Coalesces per-filename instead of first-wins: keep the
  // max rows_emitted across dupes, OR extractor_touched, prefer the longest
  // sample_head. "empty" was literally a lie before this: first-wins picked
  // the pre-extraction pass with rows_emitted=0 even when a later pass saw
  // 210 records for the same logical file.
  const dedupedFiles = $derived.by(() => {
    const byName = new Map();
    for (const f of drawerCtx.files) {
      const prev = byName.get(f.filename);
      if (!prev) {
        byName.set(f.filename, { ...f });
        continue;
      }
      prev.rows_emitted = Math.max(prev.rows_emitted || 0, f.rows_emitted || 0);
      prev.extractor_touched = prev.extractor_touched || f.extractor_touched;
      if ((f.sample_head?.length ?? 0) > (prev.sample_head?.length ?? 0)) {
        prev.sample_head = f.sample_head;
        prev.file_sha256 = f.file_sha256;
      }
      prev.size_bytes = Math.max(prev.size_bytes || 0, f.size_bytes || 0);
    }
    return Array.from(byName.values());
  });
  const systemRows = $derived(
    drawerCtx.records.filter(
      (r) =>
        r.rule_id === 'software_corporate_marker' ||
        r.rule_id === 'pc_info_block' ||
        r.rule_id === 'ui_identity_block',
    ),
  );

  const selectedFileRow = $derived(
    dedupedFiles.find((f) => f.rel_path === drawerCtx.selectedFile) ?? dedupedFiles[0],
  );

  const prevPage = () => loadArtifacts({ page: Math.max(1, listCtx.page - 1) });
  const nextPage = () => {
    const pc = listCtx.pageMeta?.page_count ?? 1;
    loadArtifacts({ page: Math.min(pc, listCtx.page + 1) });
  };

  onMount(() => loadArtifacts({ page: 1 }));
</script>

<main>
  <div class="head">
    <SectionHeader group="Stealer" slug="stealer" title="Artifacts" />
  </div>

  {#if listCtx.denied}
    <p class="note">
      This surface needs a <code>read:stealer</code> clearance grant. Ask an admin to grant it.
    </p>
  {:else if listCtx.error}
    <p class="note err">{listCtx.error}</p>
  {:else if !listCtx.loaded}
    <p class="note">Loading artifacts…</p>
  {:else if !listCtx.initialized}
    <section class="empty">
      <div class="empty-card">
        <h2>No artifacts yet</h2>
        <p>
          The stealer pipeline hasn't processed any archives. Mark a Telegram channel as a stealer
          source in Monitored Groups and come back once attachments have been extracted.
        </p>
      </div>
    </section>
  {:else}
    <section class="list">
      <div class="meta">
        <span>{fmt(listCtx.pageMeta?.total ?? 0)} artifacts</span>
        <span class="range">
          {#if listCtx.pageMeta}
            Page {listCtx.pageMeta.page} of {listCtx.pageMeta.page_count || 1}
          {/if}
        </span>
      </div>
      <div class="grid">
        {#each listCtx.items as a (a.archive_sha256 + '/' + a.victim_folder)}
          <button
            class="card"
            class:selected={drawerCtx.open
              && drawerCtx.sha === a.archive_sha256
              && drawerCtx.folder === a.victim_folder}
            data-tone={cardTone(a)}
            onclick={() => openDrawer(a.archive_sha256, a.victim_folder)}
          >
            <div class="row1">
              <span class="id">{shortSha(a.archive_sha256)}</span>
              <span class="cc">{a.country || '--'} · {a.traffic_affid || '--'}</span>
            </div>
            <div class="folder" title={a.victim_folder}>{a.victim_folder}</div>
            <div class="row3">
              <span>{fmt(a.creds_count)} creds</span>
              <span>{fmt(a.cookies_count)} cookies</span>
              {#if a.has_wallet}<span class="wallet">wallet</span>{/if}
            </div>
            <div class="build">{a.build_version || ''}</div>
          </button>
        {/each}
      </div>
      {#if listCtx.items.length === 0}
        <div class="empty-cards">No artifacts on this page.</div>
      {/if}
      <div class="pager">
        <Button
          variant="ghost"
          size="sm"
          disabled={listCtx.page <= 1 || listCtx.loading}
          onclick={prevPage}
        >
          Previous
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={listCtx.loading
            || !listCtx.pageMeta
            || !listCtx.pageMeta.has_more}
          onclick={nextPage}
        >
          Next page
        </Button>
      </div>
    </section>
  {/if}

  {#if drawerCtx.open}
    <div class="scrim" onclick={closeDrawer} role="presentation"></div>
    <aside class="drawer" aria-label="Artifact drawer">
      <header class="d-head">
        <div class="d-head-top">
          <div class="d-ident">
            <div class="d-badges">
              <span class="d-id">{shortSha(drawerCtx.sha)}</span>
              {#if drawerCtx.detail?.has_corporate_marker}
                <Badge tone="critical" dot>{'CORPORATE'}</Badge>
              {/if}
              {#if drawerCtx.detail?.first_wallet_family}
                <Badge tone="high">{drawerCtx.detail.first_wallet_family.toUpperCase()}</Badge>
              {/if}
              {#if drawerCtx.detail?.has_crypter_banner}
                <Badge tone="warn">{'AWARE'}</Badge>
              {/if}
            </div>
            <div class="d-folder">{drawerCtx.folder}</div>
            <div class="d-sub">
              {drawerCtx.detail?.computer_name || ''} ·
              {drawerCtx.detail?.user_name || ''} ·
              {drawerCtx.detail?.os_version || ''}
            </div>
          </div>
          <div class="d-actions">
            <Button variant="ghost" size="sm">Link to case</Button>
            <Button variant="ghost" size="sm">Export</Button>
            <Button variant="primary" size="sm">Pivot on host</Button>
            <Button variant="ghost" size="sm" onclick={closeDrawer}>✕</Button>
          </div>
        </div>
        <div class="d-tiles">
          <StatTile label="Credentials" value={fmt(drawerCtx.detail?.stat_tiles?.credentials)} />
          <StatTile
            label="Domain hits"
            value={fmt(drawerCtx.detail?.stat_tiles?.domain_hits)}
            tone={drawerCtx.detail?.stat_tiles?.domain_hits > 0 ? 'critical' : 'default'}
          />
          <StatTile label="Cookies" value={fmt(drawerCtx.detail?.stat_tiles?.cookies)} />
          <StatTile label="Country" value={drawerCtx.detail?.stat_tiles?.country || '--'} />
          <StatTile
            label="Related"
            value={fmt(drawerCtx.detail?.stat_tiles?.related)}
            tone="accent"
          />
        </div>
        <nav class="d-tabs">
          {#each TABS as t}
            <button
              class="tab"
              class:active={drawerCtx.tab === t.id}
              onclick={() => pickTab(t.id)}
            >
              {t.label}
            </button>
          {/each}
        </nav>
      </header>

      <div class="d-body">
        <div class="d-main">
          {#if drawerCtx.loading}
            <p class="note">Loading…</p>
          {:else if drawerCtx.error}
            <p class="note err">{drawerCtx.error}</p>
          {:else if drawerCtx.tab === 'overview'}
            <div class="overview">
              <div class="panel">
                <div class="panel-label">ASSESSMENT</div>
                <p>
                  {drawerCtx.detail?.source || 'stealer'} artifact from
                  {drawerCtx.detail?.country || 'unknown country'}.
                  {#if drawerCtx.detail?.creds_count}
                    {fmt(drawerCtx.detail.creds_count)} credentials recovered.
                  {/if}
                  {#if drawerCtx.detail?.stat_tiles?.domain_hits > 0}
                    <strong class="hit">
                      {drawerCtx.detail.stat_tiles.domain_hits} accounts match monitored domains.
                    </strong>
                  {/if}
                  {#if drawerCtx.detail?.first_wallet_family}
                    Wallet vault detected: {drawerCtx.detail.first_wallet_family}.
                  {/if}
                </p>
              </div>
              <div class="panel">
                <div class="panel-label">TECHNIQUES</div>
                <div class="techs">
                  {#each drawerCtx.detail?.techniques ?? [] as t}
                    <a class="tech" href={t.url} target="_blank" rel="noopener">
                      <span class="tid">{t.technique_id}</span>
                      <span class="tname">{t.name}</span>
                    </a>
                  {/each}
                  {#if (drawerCtx.detail?.techniques?.length ?? 0) === 0}
                    <span class="muted">No techniques derived.</span>
                  {/if}
                </div>
              </div>
            </div>
          {:else if drawerCtx.tab === 'files'}
            <table class="t">
              <thead>
                <tr>
                  <th>NAME</th><th>TYPE</th><th>SIZE</th>
                  <th title="-- = extractor never opened this file (no rule matched its shape). 0 rows = extractor opened it but no rule content-matched. N rows = N extractions landed.">SIGNAL</th>
                </tr>
              </thead>
              <tbody>
                {#each dedupedFiles as f}
                  <tr
                    class:picked={drawerCtx.selectedFile === f.rel_path}
                    onclick={() => pickFile(f.rel_path)}
                  >
                    <td class="name">{f.filename}</td>
                    <td>{f.heuristic_kind}</td>
                    <td>{fmtBytes(f.size_bytes)}</td>
                    <td>
                      {#if !f.extractor_touched}
                        <span class="sig sig-skip" title="not inspected (no rule shape matched)">--</span>
                      {:else if f.rows_emitted > 0}
                        <span class="sig sig-hit" title="{f.rows_emitted} records extracted">{fmt(f.rows_emitted)} rows</span>
                      {:else}
                        <span class="sig sig-zero" title="inspected but no records matched; may be a rule-coverage gap">0 rows</span>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
            {#if drawerCtx.files.length === 0}
              <p class="note">No files indexed for this victim.</p>
            {/if}
          {:else if drawerCtx.tab === 'credentials'}
            <table class="t t-creds">
              <colgroup>
                <col style="width:34%" />
                <col style="width:26%" />
                <col style="width:22%" />
                <col style="width:18%" />
              </colgroup>
              <thead>
                <tr>
                  <th>URL</th><th>USERNAME</th><th>PASSWORD</th><th>BROWSER</th>
                </tr>
              </thead>
              <tbody>
                {#each creds as c}
                  <tr>
                    <td class="name wrap">{credUrl(c.fields)}</td>
                    <td class="wrap">{credUser(c.fields)}</td>
                    <td class="pw wrap">{credPw(c.fields)}</td>
                    <td class="muted wrap">{credBrowser(c.fields)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
            {#if creds.length === 0}
              <p class="note">No credential rows loaded yet.</p>
            {/if}
          {:else if drawerCtx.tab === 'system'}
            <table class="t">
              <tbody>
                {#each systemRows as r}
                  {#each Object.entries(r.fields) as [k, v]}
                    <tr>
                      <td class="muted" style="width:140px">{k}</td>
                      <td class="name">{v}</td>
                    </tr>
                  {/each}
                {/each}
              </tbody>
            </table>
            {#if systemRows.length === 0}
              <p class="note">No system fingerprint rows loaded.</p>
            {/if}
          {:else if drawerCtx.tab === 'audit'}
            <p class="note">Audit stream is not wired yet (backend endpoint pending).</p>
          {/if}
        </div>

        <aside class="d-right">
          <div class="r-section">
            <div class="panel-label">SELECTED</div>
            {#if selectedFileRow}
              <div class="r-name">{selectedFileRow.filename}</div>
              <div class="r-sub">{selectedFileRow.heuristic_kind}</div>
              <pre class="r-preview">{selectedFileRow.sample_head || ''}</pre>
              <div class="r-meta">
                <span class="muted">SHA-256</span>
                <span class="mono">{shortSha(selectedFileRow.file_sha256)}</span>
                <span class="muted">SIZE</span>
                <span class="mono">{fmtBytes(selectedFileRow.size_bytes)}</span>
              </div>
            {:else}
              <div class="muted">No file selected.</div>
            {/if}
          </div>
          <div class="r-section">
            <div class="panel-label">EXTRACTED INDICATORS</div>
            {#each drawerCtx.domains.slice(0, 12) as d}
              <div class="ioc">
                <span class="dot" data-kind={d.source_kind}></span>
                <span class="ioc-v" title={d.domain}>{d.domain}</span>
                <span class="muted ioc-k">{d.source_kind}</span>
              </div>
            {/each}
            {#if drawerCtx.domains.length === 0}
              <div class="muted">No indicators extracted.</div>
            {/if}
          </div>
        </aside>
      </div>
    </aside>
  {/if}
</main>

<style>
  /* Match the layout convention from /stealer and the other primary surfaces:
     main is a flex column that fills the content area; children carry their own
     horizontal padding (:16px 20px:) so lists, tables, and the empty-state card
     all align flush with the SectionHeader above. */
  main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow: auto;
    background: var(--black);
    padding-bottom: 24px;
  }
  .head {
    padding-right: 20px;
  }
  .list,
  .empty {
    padding: 0 20px;
  }
  .list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-top: 10px;
  }
  .note {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
  }
  .note.err {
    color: var(--red-text);
  }
  .empty {
    display: flex;
    justify-content: center;
    padding-top: 64px;
  }
  .empty-card {
    width: 100%;
    max-width: 520px;
    padding: 24px;
    border: 1px solid var(--border);
    background: var(--panel);
    border-radius: var(--radius);
    text-align: center;
  }
  .meta {
    display: flex;
    justify-content: space-between;
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    color: var(--text-faint);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 10px;
  }
  .card {
    text-align: left;
    cursor: pointer;
    border: 1px solid var(--border);
    background: var(--panel);
    border-radius: var(--radius);
    padding: 12px;
    display: grid;
    gap: 6px;
    color: var(--text);
    font: inherit;
  }
  .card:hover {
    background: var(--panel-2);
  }
  .card.selected {
    border-color: var(--accent-border);
    background: var(--accent-fill);
  }
  .card[data-tone='critical'] {
    border-left: 2px solid var(--red-text);
  }
  .card[data-tone='high'] {
    border-left: 2px solid var(--accent-text);
  }
  .row1 {
    display: flex;
    justify-content: space-between;
    font-family: var(--font-mono);
    font-size: var(--fs-12);
  }
  .id {
    color: var(--accent-text);
  }
  .cc {
    color: var(--text-faint);
  }
  .folder {
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .row3 {
    display: flex;
    gap: 12px;
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    color: var(--text-muted);
  }
  .wallet {
    color: var(--accent-text);
  }
  .build {
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    color: var(--text-faint);
  }
  .empty-cards {
    padding: 32px;
    text-align: center;
    color: var(--text-faint);
    font-family: var(--font-mono);
  }
  .pager {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  /* ---------- drawer ---------- */
  .scrim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.62);
    z-index: 50;
  }
  .drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(940px, 94%);
    background: var(--panel);
    border-left: 1px solid var(--accent-border);
    display: flex;
    flex-direction: column;
    z-index: 51;
    min-width: 0;
  }
  .d-head {
    padding: 14px 16px 0;
    border-bottom: 1px solid var(--border);
  }
  .d-head-top {
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }
  .d-ident {
    flex: 1;
    min-width: 0;
  }
  .d-badges {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  .d-id {
    font-family: var(--font-mono);
    color: var(--accent-text);
    font-size: var(--fs-12);
  }
  .d-folder {
    font-family: var(--font-mono);
    font-size: var(--fs-15);
    margin-top: 8px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .d-sub {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    margin-top: 4px;
  }
  .d-actions {
    display: flex;
    gap: 6px;
  }
  .d-tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 8px;
    margin: 12px 0;
  }
  .d-tabs {
    display: flex;
    gap: 2px;
    overflow-x: auto;
  }
  .tab {
    background: none;
    border: 0;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
    padding: 8px 12px;
    font: inherit;
    cursor: pointer;
    white-space: nowrap;
  }
  .tab.active {
    color: var(--text);
    border-bottom-color: var(--accent-border);
  }
  .d-body {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  .d-main {
    flex: 1;
    min-width: 0;
    overflow: auto;
    padding: 12px 16px;
  }
  .d-right {
    width: 320px;
    border-left: 1px solid var(--border);
    background: var(--panel);
    overflow: auto;
    display: flex;
    flex-direction: column;
  }
  .r-section {
    padding: 12px 14px;
    border-bottom: 1px solid var(--border);
  }
  .panel-label {
    font-size: var(--fs-11);
    letter-spacing: var(--tracking-label);
    color: var(--text-faint);
    margin-bottom: 8px;
    text-transform: uppercase;
  }
  .r-name {
    font-family: var(--font-mono);
    font-size: var(--fs-13);
    word-break: break-all;
  }
  .r-sub {
    color: var(--text-muted);
    font-size: var(--fs-12);
    margin-top: 2px;
  }
  .r-preview {
    margin: 10px 0;
    padding: 10px;
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    line-height: 1.6;
    color: var(--text-muted);
    min-height: 90px;
    white-space: pre-wrap;
    word-break: break-all;
    overflow: auto;
    max-height: 180px;
  }
  .r-meta {
    display: grid;
    grid-template-columns: 70px 1fr;
    gap: 4px 8px;
    font-family: var(--font-mono);
    font-size: var(--fs-11);
  }
  .ioc {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 5px 0;
    border-bottom: 1px solid var(--border);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
  }
  .ioc .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--text-faint);
  }
  .ioc .dot[data-kind='credential'] { background: var(--red-text); }
  .ioc .dot[data-kind='cookie'] { background: var(--accent-text); }
  .ioc .dot[data-kind='email_webmail'] { background: var(--warn-text); }
  .ioc-v {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ioc-k {
    font-size: var(--fs-11);
  }

  /* overview panels + tech badges */
  .overview {
    display: grid;
    gap: 12px;
  }
  .panel {
    border: 1px solid var(--border);
    background: var(--panel-2);
    border-radius: var(--radius);
    padding: 12px;
  }
  .hit {
    color: var(--red-text);
  }
  .techs {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .tech {
    display: inline-flex;
    gap: 6px;
    align-items: center;
    border: 1px solid var(--border);
    padding: 3px 7px;
    border-radius: 2px;
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    color: var(--text);
    text-decoration: none;
  }
  .tech:hover {
    background: var(--panel-2);
  }
  .tid {
    color: var(--accent-text);
  }
  .tname {
    color: var(--text-muted);
  }

  /* tables */
  .t {
    width: 100%;
    border-collapse: collapse;
    font-family: var(--font-mono);
    font-size: var(--fs-12);
  }
  /* Credentials table: narrow drawer, long URLs + long browser labels
     ("Microsoft Edge (Default)") push a layout:auto table way past the
     available width. Fix the layout so column widths are respected,
     then let cell content wrap on any boundary via overflow-wrap:anywhere. */
  .t-creds {
    table-layout: fixed;
  }
  .t-creds td.wrap {
    overflow-wrap: anywhere;
    word-break: break-word;
    line-height: 1.4;
  }
  /* Signal column tones: skipped files are the most common state and should
     stay quiet; "empty" (inspected, nothing matched) gets a dim amber hint
     so it reads as "we looked, there was nothing"; actual hits are accent-
     colored because that's where the operator's eye goes. */
  .sig {
    font-family: var(--font-mono);
    font-size: var(--fs-11);
  }
  .sig-skip {
    color: var(--text-faint);
  }
  .sig-zero {
    color: var(--warn-text, var(--text-muted));
  }
  .sig-hit {
    color: var(--accent-text);
  }
  .t thead th {
    text-align: left;
    padding: 8px 12px;
    color: var(--text-faint);
    font-size: var(--fs-11);
    letter-spacing: var(--tracking-label);
    font-family: var(--font-sans);
    font-weight: 500;
    text-transform: uppercase;
  }
  .t tbody td {
    padding: 6px 12px;
    border-bottom: 1px solid var(--border);
  }
  .t tbody tr {
    cursor: pointer;
  }
  .t tbody tr:hover {
    background: var(--panel-2);
  }
  .t tbody tr.picked {
    background: var(--accent-fill);
    box-shadow: inset 2px 0 0 var(--accent-text);
  }
  .name {
    color: var(--text);
  }
  .muted {
    color: var(--text-faint);
  }
  .mono {
    font-family: var(--font-mono);
    word-break: break-all;
  }
  .pw {
    color: var(--text-muted);
  }
</style>
