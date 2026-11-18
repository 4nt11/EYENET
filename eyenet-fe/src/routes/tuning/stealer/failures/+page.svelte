<script>
  // Parse-failures workbench. Files that matched a path_glob but emitted
  // zero records, grouped by character-class fingerprint over sample_head.
  // One row per shape; expand for raw sample files; "Draft rule from file"
  // hands the sample to the rule editor pre-encoded.
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import Button from '$lib/components/Button.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import {
    listCtx,
    loadFailures,
    samplesCtx,
    loadSamples,
    statsCtx,
    loadStats,
  } from '$lib/stealerFailures.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const fmtBytes = (n) => {
    const b = Number(n ?? 0);
    if (!Number.isFinite(b) || b <= 0) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB'];
    const i = Math.min(u.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
    const v = b / 1024 ** i;
    return `${i === 0 ? v : v.toFixed(v >= 100 ? 0 : 1)} ${u[i]}`;
  };
  const shortSha = (s) => (s ? s.slice(0, 8) : '');

  // Local filter form state; apply submits. Keeps typing cheap.
  let filename = $state('');
  let heuristic_kind = $state('');
  let expanded = $state(null); // shape_sig currently expanded

  function applyFilters() {
    loadFailures({ page: 1, filename, heuristic_kind });
    expanded = null;
  }
  function clearFilters() {
    filename = '';
    heuristic_kind = '';
    loadFailures({ page: 1, filename: '', heuristic_kind: '' });
    expanded = null;
  }
  function toggleRow(sig) {
    if (expanded === sig) { expanded = null; return; }
    expanded = sig;
    loadSamples(sig);
  }
  function draftRuleFromSample(sample) {
    const payload = btoa(unescape(encodeURIComponent(JSON.stringify({
      archive_sha256: sample.archive_sha256,
      victim_folder: sample.victim_folder,
      file_path: sample.file_path,
      filename: sample.filename,
      sample_head: sample.sample_head,
      heuristic_kind: sample.heuristic_kind,
    }))));
    window.location.href = `/tuning/stealer/rules/new?from=${payload}`;
  }

  const prevPage = () => loadFailures({ page: Math.max(1, listCtx.page - 1) });
  const nextPage = () => {
    const pc = listCtx.pageMeta?.page_count ?? 1;
    loadFailures({ page: Math.min(pc, listCtx.page + 1) });
  };

  onMount(() => {
    loadStats();
    loadFailures({ page: 1 });
  });

  const coverageTone = $derived(
    statsCtx.coverage_pct < 50 ? 'critical' : statsCtx.coverage_pct < 80 ? 'accent' : 'default',
  );
  const crashTone = $derived(statsCtx.crash_files > 0 ? 'critical' : 'default');
</script>

<main>
  <div class="head">
    <SectionHeader group="Stealer" slug="stealer" title="Parse failures" />
  </div>

  {#if statsCtx.loaded && statsCtx.initialized}
    <div class="tiles">
      <StatTile
        label="Corpus coverage"
        value={statsCtx.coverage_pct.toFixed(1)}
        unit="%"
        sub="{fmt(statsCtx.parsed_files)} / {fmt(statsCtx.total_files)} files"
        tone={coverageTone}
      />
      <StatTile
        label="Parse misses"
        value={fmt(statsCtx.fail_files)}
        sub="rule matched, 0 records emitted"
      />
      <StatTile
        label="Shape buckets"
        value={fmt(statsCtx.shape_buckets)}
        sub="distinct fingerprints to triage"
      />
      <StatTile
        label="Gotractor crashes"
        value={fmt(statsCtx.crash_files)}
        sub={statsCtx.crash_files > 0 ? 'parse_error set, needs retry' : 'no hard failures'}
        tone={crashTone}
      />
    </div>
  {/if}

  <div class="filters">
    <label class="f">
      <span>filename contains</span>
      <input type="text" bind:value={filename} placeholder="passwords, cookies, .txt" onkeydown={(e) => e.key === 'Enter' && applyFilters()} />
    </label>
    <label class="f">
      <span>heuristic</span>
      <select bind:value={heuristic_kind}>
        <option value="">any</option>
        <option value="text_csv">text_csv</option>
        <option value="text_kv">text_kv</option>
        <option value="text_json">text_json</option>
        <option value="text_log">text_log</option>
        <option value="text_other">text_other</option>
      </select>
    </label>
    <Button variant="primary" size="sm" onclick={applyFilters}>Apply</Button>
    <Button variant="ghost" size="sm" onclick={clearFilters}>Clear</Button>
    <div class="spacer"></div>
    {#if listCtx.pageMeta}
      <span class="meta mono">{fmt(listCtx.pageMeta.total)} shapes · page {listCtx.pageMeta.page}/{listCtx.pageMeta.page_count || 1}</span>
    {/if}
  </div>

  {#if listCtx.denied}
    <p class="note">Needs a <code>read:stealer</code> clearance grant.</p>
  {:else if listCtx.error}
    <p class="note err">{listCtx.error}</p>
  {:else if !listCtx.loaded}
    <p class="note">Loading…</p>
  {:else if !listCtx.initialized}
    <section class="empty-card">
      <h2>No corpus</h2>
      <p>The stealer pipeline hasn't produced any file_audit rows yet. Come back once an archive has been processed.</p>
    </section>
  {:else if listCtx.items.length === 0}
    <section class="empty-card">
      <h2>Nothing to fix</h2>
      <p>No parse failures match the current filters. Either your rules cover everything in scope, or the filters are too strict.</p>
    </section>
  {:else}
    <section class="table">
      <div class="thead mono">
        <span class="col-chev"></span>
        <span class="col-shape">shape fingerprint</span>
        <span class="col-count">files</span>
        <span class="col-vic">victims</span>
        <span class="col-arc">archives</span>
        <span class="col-heur">heuristic</span>
        <span class="col-names">filenames</span>
      </div>
      {#each listCtx.items as it (it.shape_sig)}
        {@const open = expanded === it.shape_sig}
        {@const sm = samplesCtx.bySig[it.shape_sig]}
        <div class="row" class:open>
          <button class="rowhead mono" type="button" onclick={() => toggleRow(it.shape_sig)}>
            <span class="col-chev">{open ? 'v' : '>'}</span>
            <span class="col-shape shape" title={it.shape_sig}>{it.shape_preview || it.shape_sig}</span>
            <span class="col-count">{fmt(it.count)}</span>
            <span class="col-vic">{fmt(it.victims)}</span>
            <span class="col-arc">{fmt(it.archives)}</span>
            <span class="col-heur muted">{it.heuristic_kind || '--'}</span>
            <span class="col-names muted" title={it.filenames?.join(', ')}>
              {(it.filenames ?? []).slice(0, 3).join(', ')}{(it.filenames?.length ?? 0) > 3 ? ` +${it.filenames.length - 3}` : ''}
            </span>
          </button>
          {#if open}
            <div class="detail">
              <div class="sample">
                <div class="label-small">representative sample</div>
                <pre class="pbody">{it.sample || '(empty)'}</pre>
              </div>
              <div class="samples">
                <div class="samples-head">
                  <span class="label-small">sample files</span>
                  {#if sm?.items}
                    <span class="count mono">{sm.items.length}</span>
                  {/if}
                </div>
                {#if sm?.loading}
                  <div class="placeholder">Loading samples…</div>
                {:else if sm?.error}
                  <div class="placeholder err">{sm.error}</div>
                {:else if sm?.items?.length === 0}
                  <div class="placeholder">No samples returned.</div>
                {:else if sm?.items}
                  <table class="stbl">
                    <thead>
                      <tr>
                        <th>archive</th>
                        <th>victim</th>
                        <th>file</th>
                        <th class="n">size</th>
                        <th>heur</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each sm.items as s}
                        <tr>
                          <td class="mono">{shortSha(s.archive_sha256)}</td>
                          <td class="mono muted" title={s.victim_folder}>{s.victim_folder}</td>
                          <td class="mono" title={s.file_path}>{s.filename || s.file_path}</td>
                          <td class="mono n">{fmtBytes(s.size_bytes)}</td>
                          <td class="mono muted">{s.heuristic_kind || '--'}</td>
                          <td class="act">
                            <Button variant="ghost" size="sm" onclick={() => draftRuleFromSample(s)}>Draft rule</Button>
                          </td>
                        </tr>
                        <tr class="pv">
                          <td colspan="6"><pre class="pbody">{s.sample_head || '(empty)'}</pre></td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                {/if}
              </div>
            </div>
          {/if}
        </div>
      {/each}
    </section>

    <div class="pager">
      <Button variant="ghost" size="sm" disabled={listCtx.page <= 1 || listCtx.loading} onclick={prevPage}>Previous</Button>
      <Button variant="primary" size="sm" disabled={listCtx.loading || !listCtx.pageMeta?.has_more} onclick={nextPage}>Next page</Button>
    </div>
  {/if}
</main>

<style>
  main { display: flex; flex-direction: column; gap: 16px; }
  .head { display: flex; align-items: center; justify-content: space-between; }

  .tiles {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }
  @media (max-width: 900px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

  .filters {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    padding: 10px 14px; border: 1px solid var(--border); border-radius: var(--radius);
    background: var(--panel);
  }
  .f { display: flex; flex-direction: column; gap: 3px; }
  .f > span { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .f input, .f select {
    background: var(--surface); color: var(--text); border: 1px solid var(--border);
    border-radius: var(--radius-sm); padding: 4px 8px;
    font-family: var(--font-mono); font-size: var(--fs-12);
  }
  .f input { min-width: 240px; }
  .spacer { flex: 1; }
  .meta { color: var(--text-muted); font-size: var(--fs-11); letter-spacing: var(--tracking-data); text-transform: uppercase; }

  .note { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-muted); }
  .note.err { color: var(--red-text); }
  .note code { background: var(--surface); padding: 1px 6px; border-radius: var(--radius-sm); }

  .empty-card {
    border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel);
    padding: 24px; max-width: 70ch;
  }
  .empty-card h2 { margin: 0 0 6px 0; font-size: var(--fs-16); font-weight: var(--fw-semibold); color: var(--text); }
  .empty-card p { margin: 0; color: var(--text-muted); font-size: var(--fs-13); line-height: var(--lh-normal); }

  .table { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  .thead, .rowhead {
    display: grid;
    grid-template-columns: 24px minmax(0, 2.4fr) 70px 70px 70px 110px minmax(0, 1.6fr);
    align-items: center; gap: 10px;
    padding: 8px 14px;
    font-size: var(--fs-12); letter-spacing: var(--tracking-data);
  }
  .thead {
    background: var(--panel-2); border-bottom: 1px solid var(--border);
    color: var(--text-faint); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase;
  }
  .rowhead {
    width: 100%; background: transparent; border: none; border-left: 2px solid transparent;
    color: var(--text); text-align: left; cursor: pointer;
    transition: background 120ms ease;
  }
  .rowhead:hover { background: var(--panel-2); }
  .row { border-bottom: 1px solid var(--border); }
  .row:last-child { border-bottom: none; }
  .row.open > .rowhead { background: var(--panel-2); border-left-color: var(--accent-text); }
  .col-chev { color: var(--text-faint); }
  .col-shape.shape {
    color: var(--accent-text); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  .col-count, .col-vic, .col-arc { text-align: right; color: var(--text); }
  .muted { color: var(--text-faint); }
  .col-names { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  .detail {
    border-top: 1px solid var(--border);
    background: var(--surface);
    padding: 12px 14px;
    display: flex; flex-direction: column; gap: 12px;
  }
  .label-small { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .sample { display: flex; flex-direction: column; gap: 6px; }
  .pbody {
    margin: 0; padding: 10px;
    background: var(--black); border: 1px solid var(--border); border-radius: var(--radius-sm);
    color: var(--text);
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data);
    max-height: 240px; overflow: auto;
    white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
  }
  .samples { border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--panel); overflow: hidden; }
  .samples-head { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; background: var(--panel-2); border-bottom: 1px solid var(--border); }
  .samples-head .count { color: var(--accent-text); font-size: var(--fs-11); letter-spacing: var(--tracking-label); }
  .placeholder { padding: 14px; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--fs-12); }
  .placeholder.err { color: var(--red-text); }

  .stbl { width: 100%; border-collapse: collapse; }
  .stbl thead th {
    text-align: left; padding: 6px 10px; background: var(--panel); border-bottom: 1px solid var(--border);
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint);
  }
  .stbl thead th.n { text-align: right; }
  .stbl tbody tr { border-bottom: 1px solid var(--border); }
  .stbl tbody tr:last-child { border-bottom: none; }
  .stbl td {
    padding: 4px 10px; font-family: var(--font-mono); font-size: var(--fs-11);
    letter-spacing: var(--tracking-data); color: var(--text); vertical-align: top;
    max-width: 320px; word-break: break-all;
  }
  .stbl td.n { text-align: right; white-space: nowrap; }
  .stbl td.act { text-align: right; white-space: nowrap; }
  .stbl tr.pv td { padding-top: 0; padding-bottom: 6px; background: var(--surface); }
  .stbl tr.pv .pbody { max-height: 160px; }

  .pager { display: flex; justify-content: flex-end; gap: 8px; }

  .mono { font-family: var(--font-mono); letter-spacing: var(--tracking-data); }
</style>
