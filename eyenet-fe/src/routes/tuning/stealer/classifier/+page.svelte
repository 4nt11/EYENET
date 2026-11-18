<script>
  // Classifier tuning dashboard. Shows per-family precision/recall vs the
  // operator override set, per-family verdict counts, and a quick-link to
  // the family editor / reclassify CLI docs. Phases 7 (ground-truth
  // metrics) and 8 (surface) of the stealer-family classifier rollout.
  // See development/STEALER_FAMILY_CLASSIFIER_DESIGN.md.
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { apiGet, apiPost } from '$lib/api.js';

  let counts = $state([]);
  let metrics = $state([]);
  let countsErr = $state(null);
  let metricsErr = $state(null);
  let loading = $state(true);

  // Dry-run tester state
  let families = $state([]);   // full catalog (kind=stealer only)
  let picked = $state('');     // slug being edited
  let editor = $state(null);   // mutable copy of the picked family
  let drLimit = $state(200);
  let drBusy = $state(false);
  let drErr = $state(null);
  let drResult = $state(null);

  const fmt = (n) => (n ?? 0).toLocaleString();
  const pct = (v) => (v == null ? '--' : `${(v * 100).toFixed(0)}%`);

  onMount(async () => {
    const [c, m, f] = await Promise.allSettled([
      apiGet('/v1/stealer/families/counts', { auth: true }),
      apiGet('/v1/stealer/families/metrics', { auth: true }),
      apiGet('/v1/stealer/families', { auth: true }),
    ]);
    if (c.status === 'fulfilled') counts = c.value.items ?? [];
    else countsErr = c.reason?.message ?? String(c.reason);
    if (m.status === 'fulfilled') metrics = m.value.items ?? [];
    else metricsErr = m.reason?.message ?? String(m.reason);
    if (f.status === 'fulfilled')
      families = (f.value.families ?? []).filter((x) => x.kind === 'stealer');
    loading = false;
  });

  function pickFamily(slug) {
    picked = slug;
    const fam = families.find((x) => x.slug === slug);
    // Deep-copy so edits don't mutate the catalog view
    editor = fam ? JSON.parse(JSON.stringify(fam)) : null;
    drResult = null;
    drErr = null;
  }

  function parseListInput(v) {
    // Accept comma-separated or newline-separated strings for list fields
    if (!v) return [];
    return v
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  async function onDryRun() {
    if (!editor) return;
    drBusy = true;
    drErr = null;
    drResult = null;
    try {
      const r = await apiPost(
        '/v1/stealer/families/classify-dryrun',
        { families: [editor], limit: drLimit },
        { auth: true },
      );
      drResult = r;
    } catch (e) {
      drErr = e.status === 403
        ? 'needs read:stealer clearance'
        : e.status === 422
          ? `invalid family payload: ${e.message ?? ''}`
          : (e.message ?? String(e));
    } finally {
      drBusy = false;
    }
  }

  const overrideTotal = $derived(metrics.reduce((n, m) => n + m.override_count, 0));
  const verdictTotal = $derived(counts.reduce((n, c) => n + c.count, 0));
  const noVerdictCount = $derived(counts.find((c) => !c.slug)?.count ?? 0);
  const confidentShare = $derived(
    verdictTotal > 0 ? ((verdictTotal - noVerdictCount) / verdictTotal) : 0,
  );
</script>

<main>
  <div class="head">
    <SectionHeader group="Stealer" slug="classifier" title="Classifier dashboard" />
  </div>

  {#if loading}
    <p class="note">Loading…</p>
  {:else}
    <section class="tiles">
      <StatTile label="Classified victims" value={fmt(verdictTotal)} tone="accent" />
      <StatTile
        label="Confident verdicts"
        value={pct(confidentShare)}
        sub={`${fmt(verdictTotal - noVerdictCount)} / ${fmt(verdictTotal)}`}
        tone={confidentShare >= 0.75 ? 'default' : confidentShare >= 0.5 ? 'accent' : 'critical'}
      />
      <StatTile
        label="No verdict"
        value={fmt(noVerdictCount)}
        sub="ambiguous / layout-flattened"
      />
      <StatTile
        label="Ground-truth overrides"
        value={fmt(overrideTotal)}
        sub={overrideTotal === 0 ? 'no labels yet' : 'operator-provided'}
      />
    </section>

    <section class="panel">
      <header>
        <span class="n">01</span>
        <span class="label">Verdict distribution</span>
        <span class="hint">slug / count ranked by corpus share</span>
      </header>
      {#if countsErr}
        <p class="note err">{countsErr}</p>
      {:else if counts.length === 0}
        <p class="note">No verdicts persisted yet. Run <code>eyenet stealer-reclassify</code>.</p>
      {:else}
        <table class="t">
          <thead>
            <tr><th>Family</th><th class="n">Count</th><th class="n">Share</th></tr>
          </thead>
          <tbody>
            {#each counts as c}
              <tr>
                <td>
                  {#if c.slug}
                    <a href={`/stealer/families/${encodeURIComponent(c.slug)}`} class="link">{c.slug}</a>
                  {:else}
                    <span class="muted">(no verdict)</span>
                  {/if}
                </td>
                <td class="n mono">{fmt(c.count)}</td>
                <td class="n mono muted">{pct(verdictTotal ? c.count / verdictTotal : 0)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section class="panel">
      <header>
        <span class="n">02</span>
        <span class="label">Precision / recall vs overrides</span>
        <span class="hint">
          {overrideTotal === 0
            ? 'no overrides yet; use the drawer Reclassify button to label ground truth'
            : 'TP = override matches verdict; FN = override says X, verdict did not; FP = verdict says X, override says something else'}
        </span>
      </header>
      {#if metricsErr}
        <p class="note err">{metricsErr}</p>
      {:else if metrics.length === 0}
        <p class="note">No override-labeled data to compute metrics against.</p>
      {:else}
        <table class="t">
          <thead>
            <tr>
              <th>Family</th>
              <th class="n">Overrides</th>
              <th class="n">TP</th>
              <th class="n">FP</th>
              <th class="n">FN</th>
              <th class="n">Precision</th>
              <th class="n">Recall</th>
            </tr>
          </thead>
          <tbody>
            {#each metrics as m}
              <tr>
                <td><a href={`/stealer/families/${encodeURIComponent(m.slug)}`} class="link">{m.slug}</a></td>
                <td class="n mono">{fmt(m.override_count)}</td>
                <td class="n mono">{fmt(m.tp)}</td>
                <td class="n mono muted">{fmt(m.fp)}</td>
                <td class="n mono muted">{fmt(m.fn)}</td>
                <td class="n mono" class:critical={m.precision < 0.6}>{pct(m.precision)}</td>
                <td class="n mono" class:critical={m.recall < 0.6}>{pct(m.recall)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section class="panel">
      <header>
        <span class="n">03</span>
        <span class="label">Classifier dry-run</span>
        <span class="hint">edit signals, see the shift across a corpus sample without committing</span>
      </header>
      <div class="pad">
        <div class="dr-pick">
          <label>
            <span class="dr-k">Family</span>
            <select bind:value={picked} onchange={(e) => pickFamily(e.currentTarget.value)}>
              <option value="">(pick a family)</option>
              {#each families as f}
                <option value={f.slug}>{f.name || f.slug}</option>
              {/each}
            </select>
          </label>
          <label>
            <span class="dr-k">Sample size</span>
            <input type="number" bind:value={drLimit} min="1" max="500" class="mono" />
          </label>
        </div>

        {#if editor}
          <div class="dr-form">
            <label>
              <span class="dr-k">signature_files (one per line or comma)</span>
              <textarea
                rows="3"
                value={(editor.signature_files ?? []).join('\n')}
                oninput={(e) => (editor.signature_files = parseListInput(e.currentTarget.value))}
                placeholder="Passwords.txt&#10;System.txt"
              ></textarea>
            </label>
            <label>
              <span class="dr-k">signature_paths</span>
              <textarea
                rows="2"
                value={(editor.signature_paths ?? []).join('\n')}
                oninput={(e) => (editor.signature_paths = parseListInput(e.currentTarget.value))}
                placeholder="Browser/Cookies/&#10;Autofill/"
              ></textarea>
            </label>
            <label>
              <span class="dr-k">signature_rule_ids</span>
              <textarea
                rows="2"
                value={(editor.signature_rule_ids ?? []).join('\n')}
                oninput={(e) => (editor.signature_rule_ids = parseListInput(e.currentTarget.value))}
                placeholder="stealer_info_yaml&#10;environment_windows"
              ></textarea>
            </label>
            <label>
              <span class="dr-k">build_tag_regex</span>
              <input type="text" class="mono" bind:value={editor.build_tag_regex} placeholder="^mix$" />
            </label>
            <label>
              <span class="dr-k">antisignature_files</span>
              <textarea
                rows="2"
                value={(editor.antisignature_files ?? []).join('\n')}
                oninput={(e) => (editor.antisignature_files = parseListInput(e.currentTarget.value))}
                placeholder="pc_info.json"
              ></textarea>
            </label>
            <label>
              <span class="dr-k">confidence_floor</span>
              <input type="number" step="0.05" min="0" max="1" class="mono" bind:value={editor.confidence_floor} />
            </label>

            <div class="dr-actions">
              <button class="btn-primary" onclick={onDryRun} disabled={drBusy}>
                {drBusy ? 'Running…' : `Dry-run (${drLimit} victims)`}
              </button>
              <button class="btn-ghost" onclick={() => pickFamily(picked)} disabled={drBusy}>
                Reset
              </button>
              <span class="muted">
                Persist via <a class="link" href={`/tuning/stealer/families/${encodeURIComponent(picked)}`}>family editor</a>
              </span>
            </div>
            {#if drErr}<div class="dr-err">{drErr}</div>{/if}
          </div>
        {/if}

        {#if drResult}
          <div class="dr-result">
            <div class="dr-k">Sampled {drResult.sampled} victims</div>
            <table class="t">
              <thead>
                <tr><th>Family</th><th class="n">Before</th><th class="n">After</th><th class="n">Δ</th></tr>
              </thead>
              <tbody>
                {#each drResult.counts as c}
                  {@const diff = c.after - c.before}
                  <tr>
                    <td>{c.slug || '(no verdict)'}</td>
                    <td class="n mono">{fmt(c.before)}</td>
                    <td class="n mono">{fmt(c.after)}</td>
                    <td class="n mono" class:up={diff > 0} class:down={diff < 0}>
                      {diff > 0 ? '+' : ''}{fmt(diff)}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
            {#if drResult.shifts.length > 0}
              <details>
                <summary>
                  {drResult.shifts.length} victim{drResult.shifts.length === 1 ? '' : 's'} changed verdict
                </summary>
                <table class="t">
                  <thead>
                    <tr><th>Archive</th><th>Victim</th><th>Before</th><th>After</th></tr>
                  </thead>
                  <tbody>
                    {#each drResult.shifts as s}
                      <tr>
                        <td class="mono muted">{s.archive_sha256.slice(0, 8)}</td>
                        <td class="mono" title={s.victim_folder}>{s.victim_folder.slice(0, 40)}{s.victim_folder.length > 40 ? '…' : ''}</td>
                        <td class="mono muted">{s.before_slug || '(none)'} <span class="muted">{pct(s.before_confidence)}</span></td>
                        <td class="mono accent">{s.after_slug || '(none)'} <span class="muted">{pct(s.after_confidence)}</span></td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </details>
            {/if}
          </div>
        {/if}
      </div>
    </section>

    <section class="panel actions">
      <header>
        <span class="n">04</span>
        <span class="label">Full-corpus reclassify (CLI)</span>
      </header>
      <div class="pad">
        <p>Dry-run tester above is a bounded sample. For a full-corpus commit:</p>
        <pre><code class="mono">docker exec docker-stealer-processor-1 eyenet stealer-reclassify</code></pre>
        <p class="muted">
          Write the signals you tested via the <a class="link" href="/tuning/stealer/families">family editor</a> first, then run the CLI above.
        </p>
      </div>
    </section>
  {/if}
</main>

<style>
  main { display: flex; flex-direction: column; gap: 16px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  .tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
  @media (max-width: 900px) { .tiles { grid-template-columns: repeat(2, 1fr); } }

  .panel { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  .panel > header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--panel-2); border-bottom: 1px solid var(--border); }
  .panel > header .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-label); }
  .panel > header .label { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .panel > header .hint { margin-left: auto; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); }

  .t { width: 100%; border-collapse: collapse; }
  .t thead th { text-align: left; padding: 8px 14px; background: var(--panel); border-bottom: 1px solid var(--border); font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .t thead th.n { text-align: right; }
  .t tbody tr { border-bottom: 1px solid var(--border); }
  .t tbody tr:last-child { border-bottom: none; }
  .t tbody tr:hover { background: var(--surface); }
  .t td { padding: 6px 14px; font-size: var(--fs-12); color: var(--text); }
  .t td.n { text-align: right; }
  .mono { font-family: var(--font-mono); letter-spacing: var(--tracking-data); }
  .muted { color: var(--text-muted); }
  .critical { color: var(--red-text); }
  .link { color: var(--accent-text); text-decoration: none; }
  .link:hover { text-decoration: underline; }

  .note { padding: 10px 14px; font-size: var(--fs-12); color: var(--text-muted); }
  .note.err { color: var(--red-text); }
  .note code { background: var(--surface); padding: 1px 6px; border-radius: var(--radius-sm); font-family: var(--font-mono); }

  .actions .pad { padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; font-size: var(--fs-13); color: var(--text); }
  .actions code { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text); background: var(--surface); padding: 1px 6px; border-radius: var(--radius-sm); }
  .actions pre { margin: 0; padding: 10px 12px; background: var(--black); border: 1px solid var(--border); border-radius: var(--radius-sm); overflow-x: auto; }
  .actions pre code { background: transparent; padding: 0; }

  /* Dry-run tester */
  .pad { padding: 10px 14px; display: flex; flex-direction: column; gap: 10px; }
  .dr-pick { display: flex; gap: 12px; flex-wrap: wrap; }
  .dr-pick label { display: flex; flex-direction: column; gap: 3px; }
  .dr-pick select, .dr-pick input, .dr-form input, .dr-form textarea {
    background: var(--surface); color: var(--text); border: 1px solid var(--border);
    border-radius: var(--radius-sm); padding: 5px 8px;
    font-family: var(--font-mono); font-size: var(--fs-12);
  }
  .dr-pick select { min-width: 220px; }
  .dr-pick input { width: 90px; }
  .dr-k { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .dr-form { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); }
  .dr-form label { display: flex; flex-direction: column; gap: 3px; }
  .dr-form textarea { resize: vertical; min-height: 44px; }
  .dr-actions { display: flex; align-items: center; gap: 8px; margin-top: 4px; flex-wrap: wrap; }
  .btn-primary { background: var(--accent); color: white; border: 1px solid var(--accent); border-radius: var(--radius-sm); padding: 5px 12px; font-family: var(--font-mono); font-size: var(--fs-12); cursor: pointer; }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-ghost { background: transparent; color: var(--text-muted); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 5px 12px; font-family: var(--font-mono); font-size: var(--fs-12); cursor: pointer; }
  .dr-err { color: var(--red-text); font-family: var(--font-mono); font-size: var(--fs-11); }
  .dr-result { display: flex; flex-direction: column; gap: 10px; margin-top: 8px; }
  .dr-result details { padding: 6px 0; }
  .dr-result summary { cursor: pointer; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-muted); padding: 4px 0; }
  .up { color: var(--accent-text); }
  .down { color: var(--red-text); }
  .accent { color: var(--accent-text); }
</style>
