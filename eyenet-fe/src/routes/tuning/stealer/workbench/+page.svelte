<script>
  import { onMount } from 'svelte';
  import { runRules, bulkParse } from '$lib/stealer-engine/engine.js';
  import { listRules } from '$lib/stealerRulesApi.svelte.js';

  const BULK_LIMIT = 1000;


  // ---- state ----
  /** @type {import('$lib/stealer-engine/types.js').RuleSpec[]} */
  let rules = $state([]);
  let rulesLoadErr = $state(null);

  /** Loaded file list. Each entry is { path, size, text, binary }. */
  let files = $state([]);
  /** Last picked root folder name (from the first file's webkitRelativePath). */
  let rootName = $state('');
  let loadingFiles = $state(false);
  let ingestErr = $state(null);

  /** @type {import('$lib/stealer-engine/engine.js').RunResult | null} */
  let result = $state(null);
  let running = $state(false);
  let runMs = $state(0);

  // ---- derived ----
  const stats = $derived({
    files: files.length,
    textFiles: files.filter((f) => !f.binary).length,
    totalBytes: files.reduce((n, f) => n + f.size, 0),
    rules: rules.length
  });

  const containerEvals = $derived((result?.evaluations ?? []).filter((e) => e.layer === 'container'));
  const contentEvals = $derived((result?.evaluations ?? []).filter((e) => e.layer === 'content'));
  const contentMatched = $derived(contentEvals.filter((e) => e.matched));
  const fieldsTable = $derived(Object.entries(result?.fields ?? {}));

  // Per-file: how many content rules were evaluated against it and how many matched.
  // Only content evaluations carry file_path; container rules operate on the folder
  // listing, not individual files.
  const perFile = $derived.by(() => {
    /** @type {Map<string, {evaluated: number, matched: number, matchedRules: string[]}>} */
    const m = new Map();
    for (const ev of contentEvals) {
      const p = ev.file_path;
      if (!p) continue;
      const entry = m.get(p) ?? { evaluated: 0, matched: 0, matchedRules: [] };
      entry.evaluated++;
      if (ev.matched) { entry.matched++; entry.matchedRules.push(ev.rule_id); }
      m.set(p, entry);
    }
    return m;
  });

  // ---- ingest ----
  // Chromium + Firefox + Safari all accept webkitdirectory. ZIP archives are
  // NOT unpacked in the browser (same hard rule as the mockup); the operator
  // extracts first and picks the folder.
  const MAX_BYTES_PER_FILE = 10 * 1024 * 1024;

  const PREVIEW_BYTES = 16 * 1024;

  async function onFolderPick(ev) {
    ingestErr = null;
    const picked = Array.from(ev.currentTarget.files ?? []);
    if (picked.length === 0) return;
    loadingFiles = true;
    try {
      // First file's relative path tells us the root folder name.
      const firstRel = picked[0].webkitRelativePath ?? picked[0].name;
      rootName = firstRel.split('/')[0] || 'victim-folder';

      /** @type {typeof files} */
      const out = [];
      for (const f of picked) {
        const rel = f.webkitRelativePath ?? f.name;
        const pathInsideRoot = rel.startsWith(rootName + '/') ? rel.slice(rootName.length + 1) : rel;
        if (!pathInsideRoot) continue;
        out.push(await readOneFile(f, pathInsideRoot));
      }
      out.sort((a, b) => a.path.localeCompare(b.path));
      files = out;
      expandedPath = null;
      result = null;
    } catch (e) {
      ingestErr = String(e?.message ?? e);
    } finally {
      loadingFiles = false;
    }
  }

  // Read one file into the ingest record. We always keep a <= 16 KB preview
  // slice so the operator can eyeball the raw bytes while writing rules,
  // even for files the matcher skipped (too big OR binary-looking).
  async function readOneFile(f, path) {
    const base = { path, size: f.size, text: '', binary: false, reason: null, preview: '' };
    try {
      // Always read the head slice as preview text (UTF-8 w/ replacement).
      base.preview = await f.slice(0, PREVIEW_BYTES).text();
    } catch (e) {
      base.preview = '';
      base.reason = String(e?.message ?? e);
    }
    if (f.size > MAX_BYTES_PER_FILE) {
      return { ...base, binary: true, reason: base.reason ?? 'size > 10 MB; preview only' };
    }
    try {
      const text = await f.text();
      const binary = looksBinary(text, f.size);
      // On binary classification, clear text (matchers skip it) but keep the
      // preview; operator can still inspect what it looked like.
      return { ...base, text: binary ? '' : text, binary };
    } catch (e) {
      return { ...base, binary: true, reason: base.reason ?? String(e?.message ?? e) };
    }
  }

  // Click-to-expand: one file open at a time.
  let expandedPath = $state(null);
  function togglePreview(p) { expandedPath = expandedPath === p ? null : p; }

  // Memoised per-file bulk parse. Keyed by file path + rule id; computed
  // on demand when a file row is expanded. Keeps the big parses lazy.
  /** @type {Record<string, {records: any[], total: number, truncated: boolean}>} */
  let bulkCache = $state({});
  function bulkFor(file, rule) {
    const key = `${file.path}::${rule.id}`;
    if (bulkCache[key]) return bulkCache[key];
    const out = bulkParse(rule, { path: file.path, text: file.text || file.preview || '' }, BULK_LIMIT);
    bulkCache[key] = out;
    return out;
  }
  // Recompute lazily: fresh folder picks clear the cache.
  $effect(() => { if (files) bulkCache = {}; });

  function rulesForFile(path) {
    if (!result) return [];
    return result.evaluations.filter(
      (e) => e.layer === 'content' && e.matched && e.file_path === path
    );
  }

  const ruleById = $derived(new Map(rules.map((r) => [r.id, r])));
  function _getRule(id) { return ruleById.get(id); }

  function looksBinary(text, size) {
    if (!text) return size > 0;
    // Short-ish text sample to classify; don't scan 10MB files line-for-line.
    const sample = text.length > 4096 ? text.slice(0, 4096) : text;
    let nul = 0, rep = 0;
    for (let i = 0; i < sample.length; i++) {
      const c = sample.charCodeAt(i);
      if (c === 0) nul++;
      else if (c === 0xFFFD) rep++;
    }
    return nul > 2 || rep > sample.length * 0.02;
  }

  // ---- run ----
  async function onRun() {
    if (files.length === 0 || rules.length === 0) return;
    running = true;
    const t0 = performance.now();
    try {
      // Engine wants ContentInput[]; skip binaries (matchers would misfire).
      const engineFiles = files
        .filter((f) => !f.binary)
        .map((f) => ({ path: f.path, text: f.text }));
      result = runRules(rules, { rootName, files: engineFiles });
      runMs = Math.round(performance.now() - t0);
    } finally {
      running = false;
    }
  }

  onMount(async () => {
    try { rules = await listRules(); }
    catch (e) { rulesLoadErr = String(e?.message ?? e); }
  });

  // ---- helpers ----
  const fmtBytes = (n) => {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  };
</script>

<div class="wrap">
  <!-- toolbar -->
  <div class="toolbar">
    <label class="pick-btn">
      {files.length ? 'Pick another folder' : 'Pick folder'}
      <input type="file" webkitdirectory directory multiple onchange={onFolderPick} />
    </label>
    <button class="btn-primary" onclick={onRun} disabled={!files.length || !rules.length || running}>
      {running ? 'Running...' : 'Run rules'}
    </button>
    <div class="stats mono">
      {#if rootName}<span class="root">{rootName}/</span>{/if}
      <span>{stats.files} files</span>
      <span class="sep"></span>
      <span>{stats.textFiles} text</span>
      <span class="sep"></span>
      <span>{fmtBytes(stats.totalBytes)}</span>
      <span class="sep"></span>
      <span>{stats.rules} rules</span>
      {#if runMs > 0}<span class="sep"></span><span>{runMs} ms</span>{/if}
    </div>
    <div class="trust">
      <span class="dot on"></span>
      <span>Files never leave the browser.</span>
    </div>
  </div>

  {#if rulesLoadErr}
    <div class="warn">Rules load failed: <code>{rulesLoadErr}</code>. Workbench will still load files, but running is disabled.</div>
  {/if}
  {#if ingestErr}
    <div class="warn">Ingest failed: <code>{ingestErr}</code></div>
  {/if}

  <div class="cols">
    <!-- LEFT: file tree -->
    <section class="layer">
      <header>
        <span class="n">.</span>
        <span class="label">Loaded files</span>
        <span class="hint">
          {#if files.length && result}
            {[...perFile.values()].filter((p) => p.matched > 0).length} of {stats.textFiles} text files matched by a rule
          {:else if files.length}
            {rootName}/
          {:else}
            no folder loaded
          {/if}
        </span>
      </header>
      {#if !files.length}
        <div class="placeholder">
          <p>No folder loaded. Pick an extracted stealer-log or combolist folder to begin.</p>
          <p class="hint-body">Zip archives are not unpacked in the browser. Extract first, then pick the folder.</p>
        </div>
      {:else}
        <ol class="filelist mono">
          {#each files as f}
            {@const pf = perFile.get(f.path)}
            {@const open = expandedPath === f.path}
            <li
              class:binary={f.binary}
              class:hit={pf && pf.matched > 0}
              class:scanned={pf && pf.matched === 0 && pf.evaluated > 0}
              class:unscanned={result && !pf && !f.binary}
              class:open
            >
              <button class="filerow" type="button" onclick={() => togglePreview(f.path)} title={pf && pf.matchedRules.length ? pf.matchedRules.join(', ') : (f.reason ?? '')}>
                <span class="chev">{open ? 'v' : '>'}</span>
                <span class="path">{f.path}</span>
                <span class="size">{fmtBytes(f.size)}</span>
                {#if f.binary}
                  <span class="tag">binary</span>
                {:else if pf && pf.matched > 0}
                  <span class="tag ok">{pf.matched}/{pf.evaluated} hit</span>
                {:else if pf}
                  <span class="tag muted">0/{pf.evaluated}</span>
                {:else if result}
                  <span class="tag muted">no rule</span>
                {/if}
              </button>
              {#if open}
                <div class="preview">
                  <div class="pmeta">
                    <span>{f.size.toLocaleString()} B</span>
                    <span class="sep"></span>
                    {#if f.binary}
                      <span>binary · matcher skipped</span>
                      <span class="sep"></span>
                    {/if}
                    {#if f.reason}
                      <span>{f.reason}</span>
                      <span class="sep"></span>
                    {/if}
                    <span>preview {Math.min(f.text.length || f.preview.length, PREVIEW_BYTES).toLocaleString()} chars</span>
                  </div>
                  <pre class="pbody">{(f.text || f.preview || '').slice(0, PREVIEW_BYTES) || '(empty)'}</pre>
                  {#if (f.text && f.text.length > PREVIEW_BYTES) || f.size > PREVIEW_BYTES}
                    <div class="ptail">Showing first {PREVIEW_BYTES.toLocaleString()} chars of {f.size.toLocaleString()} bytes.</div>
                  {/if}

                  {#each rulesForFile(f.path) as ev}
                    {@const r = _getRule(ev.rule_id)}
                    {@const bulk = r ? bulkFor(f, r) : null}
                    {#if bulk && bulk.records.length > 0}
                      <div class="records">
                        <div class="records-head">
                          <span class="label-small">Parsed by</span>
                          <span class="id mono">{ev.rule_id}</span>
                          <span class="count mono">{bulk.records.length}{bulk.truncated ? ` / ${bulk.total}` : ''} record{bulk.records.length === 1 ? '' : 's'}</span>
                        </div>
                        <div class="records-wrap">
                          <table class="recordstbl">
                            <thead>
                              <tr>{#each Object.keys(bulk.records[0]) as k}<th>{k}</th>{/each}</tr>
                            </thead>
                            <tbody>
                              {#each bulk.records as rec}
                                <tr>{#each Object.keys(bulk.records[0]) as k}<td class="mono">{rec[k] ?? ''}</td>{/each}</tr>
                              {/each}
                            </tbody>
                          </table>
                        </div>
                        {#if bulk.truncated}
                          <div class="ptail">Showing first {bulk.records.length.toLocaleString()} of {bulk.total.toLocaleString()} records (limit {BULK_LIMIT.toLocaleString()}).</div>
                        {/if}
                      </div>
                    {/if}
                  {/each}
                </div>
              {/if}
            </li>
          {/each}
        </ol>
      {/if}
    </section>

    <!-- RIGHT: results -->
    <section class="layer results">
      <header>
        <span class="n">.</span>
        <span class="label">Result</span>
        {#if result}
          <span class="hint">{containerEvals.filter((e) => e.matched).length}/{containerEvals.length} containers · {contentMatched.length}/{contentEvals.length} content hits</span>
        {:else}
          <span class="hint">not yet run</span>
        {/if}
      </header>

      {#if !result}
        <div class="placeholder">
          <p>Load a folder and click <strong>Run rules</strong>. Output surfaces the winning family, the merged extracted fields, and the per-rule evaluation trace.</p>
        </div>
      {:else}
        <div class="result-body">
          <div class="family-strip">
            <span class="label-small">FAMILY</span>
            <span class="family-big">{result.family ?? '(none)'}</span>
          </div>

          <div class="block">
            <div class="block-head">
              <span class="label-small">Extracted fields</span>
              <span class="count">{fieldsTable.length}</span>
            </div>
            {#if fieldsTable.length === 0}
              <div class="empty-inline">No fields extracted.</div>
            {:else}
              <table class="kv">
                <tbody>
                  {#each fieldsTable as [k, v]}
                    <tr>
                      <td class="kv-k mono">{k}</td>
                      <td class="kv-v mono">{v}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            {/if}
          </div>

          <div class="block">
            <div class="block-head">
              <span class="label-small">Rule trace</span>
              <span class="count">{result.evaluations.length}</span>
            </div>
            <table class="trace">
              <thead>
                <tr><th>Layer</th><th>Rule</th><th>File</th><th>Family</th><th>Pri</th><th>Hit</th><th>Why</th></tr>
              </thead>
              <tbody>
                {#each result.evaluations as ev}
                  <tr class:matched={ev.matched} class:miss={!ev.matched}>
                    <td class="mono muted">{ev.layer === 'container' ? 'L1' : 'L3'}</td>
                    <td class="mono id">{ev.rule_id}</td>
                    <td class="mono muted file-cell">{ev.file_path ?? (ev.layer === 'container' ? '(folder)' : '')}</td>
                    <td class="mono muted">{ev.family}</td>
                    <td class="mono muted n">{ev.priority}</td>
                    <td class="status"><span class="dot" class:on={ev.matched}></span></td>
                    <td class="mono muted">{ev.matched ? (ev.fields && Object.keys(ev.fields).length ? `${Object.keys(ev.fields).length} fields` : 'ok') : (ev.reason ?? 'no match')}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      {/if}
    </section>
  </div>
</div>

<style>
  .wrap { display: flex; flex-direction: column; gap: 16px; }

  .toolbar {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
    flex-wrap: wrap;
  }
  .pick-btn {
    background: transparent; color: var(--text-muted); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 6px 12px;
    font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    cursor: pointer; transition: background 120ms ease, color 120ms ease;
  }
  .pick-btn:hover { background: var(--panel-2); color: var(--text); }
  .pick-btn input[type="file"] { display: none; }

  .btn-primary {
    background: var(--accent); color: white; border: 1px solid var(--accent);
    border-radius: var(--radius); padding: 6px 14px;
    font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    cursor: pointer; transition: background 120ms ease;
  }
  .btn-primary:hover:not(:disabled) { background: var(--accent-hover); border-color: var(--accent-hover); }
  .btn-primary:disabled { opacity: .45; cursor: not-allowed; }

  .stats { display: flex; align-items: center; gap: 10px; color: var(--text-muted); font-size: var(--fs-11); letter-spacing: var(--tracking-data); text-transform: uppercase; }
  .stats .root { color: var(--accent-text); text-transform: none; }
  .stats .sep { width: 1px; height: 12px; background: var(--border); }

  .trust { margin-left: auto; display: flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); }
  .trust .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-text); }

  .warn {
    padding: 10px 14px;
    border: 1px solid var(--red-fill-strong); border-radius: var(--radius);
    background: var(--red-fill);
    color: var(--red-text);
    font-family: var(--font-mono); font-size: var(--fs-12);
  }
  .warn code { color: var(--text); background: var(--surface); padding: 1px 6px; border-radius: var(--radius-sm); }

  .cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: 16px; align-items: flex-start; }
  @media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }

  .layer { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  .layer > header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--panel-2); border-bottom: 1px solid var(--border); }
  .layer > header .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-label); }
  .layer > header .label { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .layer > header .hint { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); flex: 1; }

  .placeholder { padding: 24px; color: var(--text-muted); }
  .placeholder p { margin: 0 0 8px 0; font-size: var(--fs-13); }
  .placeholder .hint-body { color: var(--text-faint); font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .placeholder strong { color: var(--accent-text); font-weight: var(--fw-regular); }

  .filelist { margin: 0; padding: 0; list-style: none; max-height: 640px; overflow: auto; }
  .filelist li { border-bottom: 1px solid var(--border); }
  .filelist li:last-child { border-bottom: none; }
  .filelist li.hit > .filerow { border-left: 2px solid var(--accent-text); background: var(--accent-fill); }
  .filelist li.hit > .filerow .path { color: var(--accent-text); }
  .filelist li.scanned > .filerow { border-left: 2px solid var(--border-strong); }
  .filelist li.unscanned > .filerow { color: var(--text-faint); }
  .filelist li.binary > .filerow { color: var(--text-faint); }
  .filelist li.open > .filerow { background: var(--panel-2); }

  .filerow {
    width: 100%;
    display: flex; align-items: center; gap: 10px;
    padding: 5px 14px;
    background: transparent; border: none; border-left: 2px solid transparent;
    color: inherit; font-family: var(--font-mono); font-size: var(--fs-12);
    letter-spacing: var(--tracking-data);
    text-align: left; cursor: pointer;
    transition: background 120ms ease;
  }
  .filerow:hover { background: var(--panel-2); }
  .filerow .chev { width: 10px; color: var(--text-faint); font-size: var(--fs-11); }
  .filerow .path { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .filerow .size { color: var(--text-faint); font-size: var(--fs-11); }
  .filerow .tag { font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); padding: 1px 6px; border: 1px solid var(--border); border-radius: var(--radius-sm); }
  .filerow .tag.ok { color: var(--accent-text); border-color: var(--accent); background: var(--accent-fill); }
  .filerow .tag.muted { color: var(--text-faint); }

  .preview {
    background: var(--surface); border-top: 1px solid var(--border);
    padding: 10px 14px;
    display: flex; flex-direction: column; gap: 8px;
  }
  .pmeta { display: flex; align-items: center; gap: 10px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .pmeta .sep { width: 1px; height: 10px; background: var(--border); }
  .pbody {
    margin: 0; padding: 10px;
    background: var(--black); border: 1px solid var(--border); border-radius: var(--radius);
    color: var(--text);
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data);
    max-height: 400px; overflow: auto;
    white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
  }
  .ptail { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-data); }

  .records {
    margin-top: 12px;
    border: 1px solid var(--border); border-radius: var(--radius);
    background: var(--panel); overflow: hidden;
  }
  .records-head { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--panel-2); border-bottom: 1px solid var(--border); }
  .records-head .id { color: var(--accent-text); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  .records-head .count { margin-left: auto; color: var(--text-muted); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; }
  .records-wrap { max-height: 320px; overflow: auto; }
  .recordstbl { width: 100%; border-collapse: collapse; }
  .recordstbl thead th {
    position: sticky; top: 0;
    text-align: left; padding: 6px 10px;
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label); text-transform: uppercase;
    color: var(--text-faint);
    background: var(--panel); border-bottom: 1px solid var(--border);
  }
  .recordstbl tbody tr { border-bottom: 1px solid var(--border); }
  .recordstbl tbody tr:last-child { border-bottom: none; }
  .recordstbl tbody tr:hover { background: var(--surface); }
  .recordstbl td {
    padding: 4px 10px;
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data);
    color: var(--text); vertical-align: top;
    word-break: break-all; max-width: 260px;
  }

  .result-body { padding: 14px; display: flex; flex-direction: column; gap: 14px; }

  .family-strip { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); }
  .label-small { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .family-big { font-family: var(--font-mono); font-size: var(--fs-18); color: var(--accent-text); font-weight: var(--fw-semibold); }

  .block { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); overflow: hidden; }
  .block-head { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: var(--panel); border-bottom: 1px solid var(--border); }
  .block-head .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); letter-spacing: var(--tracking-label); }

  .empty-inline { padding: 14px; color: var(--text-faint); font-family: var(--font-mono); font-size: var(--fs-12); }

  .kv { width: 100%; border-collapse: collapse; }
  .kv tr { border-bottom: 1px solid var(--border); }
  .kv tr:last-child { border-bottom: none; }
  .kv td { padding: 6px 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  .kv .kv-k { color: var(--text-faint); width: 180px; }
  .kv .kv-v { color: var(--text); word-break: break-all; }

  .trace { width: 100%; border-collapse: collapse; }
  .trace thead th { text-align: left; padding: 8px 12px; font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); border-bottom: 1px solid var(--border); background: var(--panel); }
  .trace tbody tr { border-bottom: 1px solid var(--border); }
  .trace tbody tr:last-child { border-bottom: none; }
  .trace td { padding: 6px 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text); vertical-align: middle; }
  .trace .mono { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  .trace .muted { color: var(--text-muted); }
  .trace .id { color: var(--accent-text); }
  .trace td.n { text-align: right; width: 50px; }
  .trace td.file-cell { max-width: 260px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .trace td.status { width: 40px; text-align: center; }
  .trace .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); }
  .trace .dot.on { background: var(--accent-text); }
  .trace tr.matched td.mono.muted:last-of-type { color: var(--text); }
</style>
