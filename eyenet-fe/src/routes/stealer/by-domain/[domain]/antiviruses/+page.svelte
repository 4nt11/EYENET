<script>
  // Antiviruses tab, per OG mockup. One row per AV product aggregated
  // across the victim pool for this domain, plus a trailing null-AV row
  // ("no AV detected") reconstructed from (domain_total - sum(named)).
  //
  // The two operator-value signals are the "AV state at infection" bar
  // (how many victims had the AV ACTIVE vs DISABLED vs UNKNOWN when they
  // got leaked) and the "bypass rate" (active / total for this AV -
  // high bypass rate = the AV FAILED, the stealer got creds anyway).
  // Two toggles: null-AV shown/hidden, and whether the % column
  // denominator is the whole domain pool or just victims with known AV.
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import Shield from 'phosphor-svelte/lib/Shield';
  import { antivirusesCtx, loadDomainAntiviruses } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const pct = (num, denom) => (denom > 0 ? (num / denom) * 100 : 0);
  const pctStr = (num, denom) => `${pct(num, denom).toFixed(1)}%`;
  const relTime = (iso) => {
    if (!iso) return '-';
    const d = new Date(iso);
    const diffSec = (Date.now() - d.getTime()) / 1000;
    if (!Number.isFinite(diffSec) || diffSec < 0) return iso;
    if (diffSec < 60) return `${Math.round(diffSec)}s ago`;
    if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
    if (diffSec < 86400 * 30) return `${Math.round(diffSec / 86400)}d ago`;
    if (diffSec < 86400 * 365) return `${Math.round(diffSec / (86400 * 30))}mo ago`;
    return `${Math.round(diffSec / (86400 * 365))}y ago`;
  };

  let domain = $derived($page.params.domain);

  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainAntiviruses(domain);
    }
  });

  // Toggles: null-AV visibility + % denominator source.
  let showNullAv = $state(true);
  let pctBasedOn = $state('domain');   // 'domain' | 'known'

  // Derived rows + null-AV reconstruction.
  const knownAvVictims = $derived(
    (antivirusesCtx.items ?? []).reduce((s, r) => s + (r.victim_count || 0), 0),
  );
  const nullAvCount = $derived(
    Math.max(0, (antivirusesCtx.domain_total_victims || 0) - knownAvVictims),
  );
  const denom = $derived(pctBasedOn === 'known' ? knownAvVictims : antivirusesCtx.domain_total_victims);
  const displayRows = $derived.by(() => {
    const items = antivirusesCtx.items ?? [];
    const rows = items.map((r) => ({ ...r, isNullRow: false }));
    if (showNullAv && nullAvCount > 0) {
      rows.push({
        av_name: 'no AV detected',
        victim_count: nullAvCount,
        active_count: 0,
        disabled_count: 0,
        unknown_count: nullAvCount,
        first_seen_at: null,
        last_seen_at: null,
        isNullRow: true,
      });
    }
    return rows;
  });

  // Bypass colour thresholds: >=60% red (AV failing), 30-60% amber, <30% green.
  const bypassColour = (bp) => bp >= 60 ? 'bypass-high' : (bp >= 30 ? 'bypass-mid' : 'bypass-low');
</script>

<section class="wrap">
  <div class="url-hint">GET /v1/stealer/by-domain/{domain}/antiviruses</div>

  {#if antivirusesCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if antivirusesCtx.error}
    <div class="banner-error">{antivirusesCtx.error}</div>
  {:else if antivirusesCtx.loaded && antivirusesCtx.items.length === 0 && nullAvCount === 0}
    <div class="empty">
      No AV fingerprint data captured for <code>{domain}</code>.
    </div>
  {:else}
    <div class="toolbar">
      <div class="toolgrp">
        <span class="toolgrp-label">NULL-AV ROW</span>
        <div class="seg">
          <button class="seg-btn" class:on={showNullAv} onclick={() => (showNullAv = true)}>Shown</button>
          <button class="seg-btn" class:on={!showNullAv} onclick={() => (showNullAv = false)}>Hidden</button>
        </div>
      </div>
      <div class="toolgrp">
        <span class="toolgrp-label">% BASED ON</span>
        <div class="seg">
          <button class="seg-btn" class:on={pctBasedOn === 'domain'} onclick={() => (pctBasedOn = 'domain')}>Domain total</button>
          <button class="seg-btn" class:on={pctBasedOn === 'known'} onclick={() => (pctBasedOn = 'known')}>Known-AV subset</button>
        </div>
      </div>
      <div class="legend">
        <span class="lg-dot lg-active"></span> active
        <span class="lg-dot lg-disabled"></span> disabled
        <span class="lg-dot lg-unknown"></span> unknown
      </div>
    </div>

    <div class="table-wrap">
      <table class="av">
        <thead>
          <tr>
            <th>Antivirus</th>
            <th class="n">Victims</th>
            <th class="n">% of domain</th>
            <th>AV state at infection</th>
            <th>Bypass rate</th>
            <th>First seen</th>
            <th>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {#each displayRows as r (r.av_name)}
            {@const stateTotal = r.active_count + r.disabled_count + r.unknown_count}
            {@const activePct = pct(r.active_count, stateTotal)}
            {@const disabledPct = pct(r.disabled_count, stateTotal)}
            {@const unknownPct = pct(r.unknown_count, stateTotal)}
            {@const bypass = pct(r.active_count, r.victim_count)}
            <tr class:null-row={r.isNullRow}>
              <td class="av-name">
                <Shield size={14} weight="regular" />
                <span class:italic={r.isNullRow}>{r.av_name}</span>
              </td>
              <td class="mono n">{fmt(r.victim_count)}</td>
              <td class="mono n pct-cell">{pctStr(r.victim_count, denom)}</td>
              <td class="state-cell">
                <div class="state-bar">
                  <div class="st-seg st-active" style="width: {activePct}%" title="active: {fmt(r.active_count)}"></div>
                  <div class="st-seg st-disabled" style="width: {disabledPct}%" title="disabled: {fmt(r.disabled_count)}"></div>
                  <div class="st-seg st-unknown" style="width: {unknownPct}%" title="unknown: {fmt(r.unknown_count)}"></div>
                </div>
              </td>
              <td class="bypass-cell">
                {#if r.isNullRow || r.victim_count === 0}
                  <span class="dash">-</span>
                {:else}
                  <div class="bypass-row">
                    <div class="bypass-bar">
                      <div class="bp-fill {bypassColour(bypass)}" style="width: {bypass}%"></div>
                    </div>
                    <span class="bp-num mono {bypassColour(bypass)}">{bypass.toFixed(1)}%</span>
                  </div>
                {/if}
              </td>
              <td class="mono rel">{r.isNullRow ? '-' : relTime(r.first_seen_at)}</td>
              <td class="mono rel">{r.isNullRow ? '-' : relTime(r.last_seen_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="meta">
      Showing {fmt(displayRows.length)} of {fmt(displayRows.length)}
    </div>
  {/if}
</section>

<style>
  .wrap { display: flex; flex-direction: column; gap: 14px; }
  .url-hint { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }

  .banner-warn, .banner-error {
    padding: 10px 14px; border-radius: 3px; font-family: var(--font-sans); font-size: var(--fs-13);
  }
  .banner-warn { border: 1px solid var(--warn-fill); background: var(--warn-fill); color: var(--warn-text); }
  .banner-error { border: 1px solid var(--red-fill); background: var(--red-fill); color: var(--red-text); }
  .banner-warn code { font-family: var(--font-mono); background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 2px; }

  .empty {
    padding: 30px; text-align: center; color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13);
    border: 1px dashed var(--border); border-radius: 4px;
  }
  .empty code { font-family: var(--font-mono); color: var(--text-body); background: var(--panel); padding: 1px 4px; border-radius: 2px; }

  /* Toolbar: two segmented toggles + legend. Border frames it so it reads
     as a controls strip, not inline with the table. */
  .toolbar {
    display: flex; align-items: center; gap: 24px; flex-wrap: wrap;
    padding: 10px 14px; border: 1px solid var(--border); border-radius: 4px;
  }
  .toolgrp { display: inline-flex; align-items: center; gap: 10px; }
  .toolgrp-label {
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-medium);
    color: var(--text-muted); text-transform: uppercase; letter-spacing: var(--tracking-label);
  }
  .seg {
    display: inline-flex; border: 1px solid var(--border); border-radius: 3px; overflow: hidden;
  }
  .seg-btn {
    appearance: none; background: transparent; color: var(--text-body); border: 0;
    padding: 4px 12px; font-family: var(--font-sans); font-size: var(--fs-12); cursor: pointer;
  }
  .seg-btn:hover { color: var(--accent-text); }
  .seg-btn + .seg-btn { border-left: 1px solid var(--border); }
  .seg-btn.on {
    background: var(--accent-fill); color: var(--accent-text); font-weight: var(--fw-medium);
  }
  .legend {
    margin-left: auto; display: inline-flex; align-items: center; gap: 10px;
    font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-muted);
  }
  .lg-dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px; }
  .lg-active { background: var(--accent-text); }
  .lg-disabled { background: var(--text-muted); }
  .lg-unknown { background: var(--text-faint); }

  .table-wrap { border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
  table.av { width: 100%; border-collapse: collapse; }
  table.av th, table.av td {
    padding: 11px 14px; border-bottom: 1px solid var(--border); text-align: left;
    font-family: var(--font-sans); font-size: var(--fs-12);
  }
  table.av thead th {
    background: var(--panel); color: var(--text-muted); font-weight: var(--fw-medium);
    text-transform: uppercase; font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    position: sticky; top: 0; z-index: 1;
  }
  table.av tr:last-child td { border-bottom: 0; }
  table.av tr:hover td { background: rgba(255,255,255,0.015); }
  table.av th.n, table.av td.n { text-align: right; }

  td.av-name {
    display: inline-flex; align-items: center; gap: 8px; color: var(--text); min-width: 220px;
  }
  td.av-name :global(svg) { color: var(--text-muted); flex-shrink: 0; }
  .italic { font-style: italic; color: var(--text-muted); }
  td.pct-cell { color: var(--text-muted); width: 110px; }
  td.n { width: 90px; }
  td.rel { color: var(--text-muted); width: 100px; }
  .null-row td { color: var(--text-muted); }
  .null-row td.av-name :global(svg) { color: var(--text-faint); }

  /* State bar: three stacked segments, shared hairline. Each segment
     reads the stealer's captured state at infection time. */
  td.state-cell { min-width: 180px; }
  .state-bar {
    display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: rgba(255,255,255,0.04);
  }
  .st-seg { height: 100%; transition: width 180ms ease; }
  .st-active { background: var(--accent-text); }
  .st-disabled { background: var(--text-muted); }
  .st-unknown { background: var(--text-faint); opacity: 0.4; }

  /* Bypass bar + numeric. Colour tracks threshold: high = red (AV failed), */
  /* mid = amber, low = green. The number mirrors the bar's colour. */
  td.bypass-cell { min-width: 180px; }
  .bypass-row { display: inline-flex; align-items: center; gap: 12px; width: 100%; }
  .bypass-bar {
    flex: 1; height: 6px; background: rgba(255,255,255,0.04); border-radius: 3px; overflow: hidden;
    max-width: 140px;
  }
  .bp-fill { height: 100%; border-radius: 3px; transition: width 180ms ease; }
  .bp-num { font-size: var(--fs-13); font-weight: var(--fw-medium); min-width: 54px; text-align: left; }
  .bypass-high, .bp-fill.bypass-high { background: var(--red-text); color: var(--red-text); }
  .bypass-mid, .bp-fill.bypass-mid { background: var(--warn-text); color: var(--warn-text); }
  .bypass-low, .bp-fill.bypass-low { background: var(--text-ok, #5bbf80); color: var(--text-ok, #5bbf80); }
  .bp-num.bypass-high, .bp-num.bypass-mid, .bp-num.bypass-low { background: none; }
  .dash { color: var(--text-faint); font-family: var(--font-mono); }

  .meta { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); padding-top: 4px; }
</style>
