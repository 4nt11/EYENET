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
  import { apiGet } from '$lib/api.js';

  let counts = $state([]);
  let metrics = $state([]);
  let countsErr = $state(null);
  let metricsErr = $state(null);
  let loading = $state(true);

  const fmt = (n) => (n ?? 0).toLocaleString();
  const pct = (v) => (v == null ? '--' : `${(v * 100).toFixed(0)}%`);

  onMount(async () => {
    const [c, m] = await Promise.allSettled([
      apiGet('/v1/stealer/families/counts', { auth: true }),
      apiGet('/v1/stealer/families/metrics', { auth: true }),
    ]);
    if (c.status === 'fulfilled') counts = c.value.items ?? [];
    else countsErr = c.reason?.message ?? String(c.reason);
    if (m.status === 'fulfilled') metrics = m.value.items ?? [];
    else metricsErr = m.reason?.message ?? String(m.reason);
    loading = false;
  });

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

    <section class="panel actions">
      <header>
        <span class="n">03</span>
        <span class="label">Iteration</span>
      </header>
      <div class="pad">
        <p>
          Change a family's signal YAML at <code>eyenet/stealer/families/&lt;slug&gt;.yaml</code>
          (editor at <a class="link" href="/tuning/stealer/families">/tuning/stealer/families</a>),
          then re-run the classifier to see the shift:
        </p>
        <pre><code class="mono">docker exec docker-stealer-processor-1 eyenet stealer-reclassify</code></pre>
        <p class="muted">
          Dry-run a change first with <code>--dry-run --limit 50</code>; the CLI prints verdicts
          without persisting so you can diff before/after without touching the verdict table.
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
</style>
