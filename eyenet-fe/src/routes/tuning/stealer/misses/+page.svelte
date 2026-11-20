<script>
  // Parse misses: per-stealer-family fingerprint coverage. The gap column
  // is where new userinfo_*_shape rules unlock victims. "Parse misses" is
  // sibling to "Parse failures" (that tab lists FILES that matched a glob
  // but emitted zero records; this tab lists VICTIMS where NO fingerprint
  // rule fired at all, grouped by stealer family).
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Button from '$lib/components/Button.svelte';
  import { coverageCtx, loadRuleCoverage } from '$lib/stealerRuleCoverage.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const pct = (n) => `${(n ?? 0).toFixed(1)}%`;

  // Ranked by missing_fingerprint desc server-side; the biggest row is the
  // top ROI target for rule authoring. Cap the bar width to the largest
  // missing bucket in view.
  const rowsWithBars = $derived.by(() => {
    const items = coverageCtx.items ?? [];
    const max = Math.max(1, ...items.map((r) => r.missing_fingerprint));
    return items.map((r) => ({
      ...r,
      bar_pct: Math.round((r.missing_fingerprint / max) * 100),
    }));
  });

  onMount(loadRuleCoverage);
</script>

<main>
  <div class="head">
    <SectionHeader group="Tuning > stealer" slug="misses" title="Parse misses" />
    <p class="desc">
      For every stealer family the classifier identifies, how many victims have
      <em>no fingerprint extraction</em>. The biggest gap is the next rule to write.
      Refreshes on load; no live subscription.
    </p>
    <div class="actions">
      <Button variant="ghost" on:click={loadRuleCoverage} disabled={coverageCtx.loading}>
        {coverageCtx.loading ? 'Loading...' : 'Refresh'}
      </Button>
    </div>
  </div>

  {#if coverageCtx.denied}
    <div class="banner banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if coverageCtx.error}
    <div class="banner banner-error">{coverageCtx.error}</div>
  {:else}
    <section class="tiles">
      <StatTile label="Total victims" value={fmt(coverageCtx.total_victims)} />
      <StatTile label="Fingerprint coverage" value={pct(coverageCtx.coverage_pct)} />
      <StatTile label="Victims with no fingerprint" value={fmt(coverageCtx.total_missing)} />
    </section>

    {#if coverageCtx.loaded && rowsWithBars.length === 0 && !coverageCtx.loading}
      <div class="empty">
        No rows. Either the corpus is empty, or every family has fewer than 5
        victims (threshold).
      </div>
    {:else}
      <section class="table-wrap">
        <table class="misses">
          <thead>
            <tr>
              <th class="l">Stealer family</th>
              <th class="r">Victims</th>
              <th class="r">With fingerprint</th>
              <th class="r">Missing</th>
              <th class="r">Miss %</th>
              <th class="bar">Gap</th>
            </tr>
          </thead>
          <tbody>
            {#each rowsWithBars as row (row.stealer_family)}
              <tr>
                <td class="fam">{row.stealer_family}</td>
                <td class="r">{fmt(row.total_victims)}</td>
                <td class="r g">{fmt(row.with_fingerprint)}</td>
                <td class="r b">{fmt(row.missing_fingerprint)}</td>
                <td class="r b">{pct(row.missing_pct)}</td>
                <td class="bar">
                  <div class="bar-track"><div class="bar-fill" style="width:{row.bar_pct}%"></div></div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>

      <aside class="hint">
        <h3>How to read this</h3>
        <p>
          A family with <strong>100% miss</strong> means we classify its archives but no
          <code>userinfo_*_shape</code> rule fires against them. Write a rule targeting
          that stealer's output format and the gap closes on the next reindex pass.
        </p>
        <p>
          The <code>unknown</code> row is upstream of this: those archives failed the
          family classifier itself. Fingerprint extraction may still run (via
          generic rules like <code>userinfo_json_v2_shape</code>) but the family
          verdict stays empty until a <em>container</em> rule fires.
        </p>
      </aside>
    {/if}
  {/if}
</main>

<style>
  main { display: flex; flex-direction: column; gap: 18px; }
  .head { display: flex; flex-direction: column; gap: 10px; }
  .desc { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); max-width: 80ch; }
  .desc em { color: var(--text-body); font-style: normal; font-weight: var(--fw-medium); }
  .actions { display: flex; gap: 8px; }

  .banner { padding: 10px 14px; border-radius: 4px; font-family: var(--font-sans); font-size: var(--fs-13); }
  .banner-warn { background: var(--surface-warn, #332514); color: var(--text-warn, #e3a85b); border: 1px solid var(--border); }
  .banner-error { background: var(--surface-error, #331818); color: var(--text-error, #e86a6a); border: 1px solid var(--border); }
  .banner code { font-family: var(--font-mono); font-size: var(--fs-12); background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 2px; }

  .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }

  .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 4px; }
  table.misses { width: 100%; border-collapse: collapse; font-family: var(--font-mono); font-size: var(--fs-12); }
  table.misses th, table.misses td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
  table.misses th { background: var(--surface-elevated, rgba(255,255,255,0.03)); text-align: left; color: var(--text-muted); font-weight: var(--fw-medium); letter-spacing: var(--tracking-label); text-transform: uppercase; font-size: var(--fs-11); }
  table.misses th.r, table.misses td.r { text-align: right; }
  table.misses th.l { text-align: left; }
  table.misses tr:last-child td { border-bottom: 0; }
  td.fam { color: var(--text); font-weight: var(--fw-medium); }
  td.g { color: var(--text-ok, #5bbf80); }
  td.b { color: var(--text-warn, #e3a85b); }
  td.bar { width: 25%; min-width: 120px; }
  .bar-track { height: 6px; background: rgba(255,255,255,0.05); border-radius: 3px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--text-warn, #e3a85b); border-radius: 3px; transition: width 150ms ease; }

  .empty { padding: 20px; text-align: center; color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); }

  aside.hint { border: 1px dashed var(--border); border-radius: 4px; padding: 14px 16px; background: rgba(255,255,255,0.015); }
  aside.hint h3 { margin: 0 0 6px; font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); letter-spacing: var(--tracking-label); text-transform: uppercase; }
  aside.hint p { margin: 6px 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }
  aside.hint code { font-family: var(--font-mono); font-size: var(--fs-12); background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 2px; color: var(--text-body); }
  aside.hint strong { color: var(--text); font-weight: var(--fw-medium); }
</style>
