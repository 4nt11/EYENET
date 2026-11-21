<script>
  // Samples tab, per OG mockup. One row per distinct loader MD5 across
  // the domain's victim pool, ranked by victim count. Core operator
  // workflow: identify the stealer binary that keeps infecting, then
  // feed its MD5 to the client's EDR as a block indicator. Click a row
  // to expand and see loader paths + per-AV bypass breakdown for that
  // specific sample.
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import CaretDown from 'phosphor-svelte/lib/CaretDown';
  import Copy from 'phosphor-svelte/lib/Copy';
  import Info from 'phosphor-svelte/lib/Info';
  import { samplesCtx, loadDomainSamples, loadSampleDetail } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const shortMd5 = (s) => (s ? s.slice(0, 8) : '');
  const pctStr = (num, denom) => (denom > 0 ? `${((num / denom) * 100).toFixed(0)}%` : '0%');
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
  const bypassColour = (rate) => {
    const pct = (rate || 0) * 100;
    if (pct >= 60) return 'bp-high';
    if (pct >= 30) return 'bp-mid';
    return 'bp-low';
  };

  let domain = $derived($page.params.domain);
  onMount(() => loadDomainSamples(domain));

  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainSamples(domain);
    }
  });

  // Null-sample row: domain victims that have no fingerprint with payload_md5.
  const namedVictimTotal = $derived(
    (samplesCtx.items ?? []).reduce((s, r) => s + (r.victim_count || 0), 0),
  );
  const nullSampleCount = $derived(
    Math.max(0, (samplesCtx.domain_total_victims || 0) - namedVictimTotal),
  );
  // Volume bar scales relative to the top-victim-count row.
  const maxVictimCount = $derived(
    Math.max(1, ...(samplesCtx.items ?? []).map((r) => r.victim_count || 0)),
  );

  // Expansion state + per-md5 detail cache (ctx-level cache lives in the
  // loader; this map is the per-render cache of fetched details).
  let expanded = $state(new Set());
  let details = $state({});
  let detailLoading = $state(new Set());

  async function toggle(md5) {
    const next = new Set(expanded);
    if (next.has(md5)) {
      next.delete(md5);
      expanded = next;
      return;
    }
    next.add(md5);
    expanded = next;
    if (details[md5]) return;
    const nl = new Set(detailLoading);
    nl.add(md5);
    detailLoading = nl;
    try {
      const data = await loadSampleDetail(domain, md5);
      details = { ...details, [md5]: data };
    } catch { /* noop */ }
    const nl2 = new Set(detailLoading);
    nl2.delete(md5);
    detailLoading = nl2;
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text ?? ''); } catch { /* ignore */ }
  }

  const displayLimit = $derived((samplesCtx.items ?? []).length + (nullSampleCount > 0 ? 1 : 0));
</script>

<section class="wrap">
  <div class="url-hint">GET /v1/stealer/by-domain/{domain}/samples?limit=50</div>

  {#if samplesCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if samplesCtx.error}
    <div class="banner-error">{samplesCtx.error}</div>
  {:else if samplesCtx.loaded && samplesCtx.items.length === 0 && nullSampleCount === 0}
    <div class="empty">
      No loader metadata captured for <code>{domain}</code>.
    </div>
  {:else}
    <div class="samples">
      {#each samplesCtx.items as r (r.loader_md5)}
        {@const isOpen = expanded.has(r.loader_md5)}
        {@const barPct = Math.max(2, Math.round((r.victim_count / maxVictimCount) * 100))}
        {@const detail = details[r.loader_md5]}
        {@const loading = detailLoading.has(r.loader_md5)}
        <div class="sample" class:open={isOpen}>
          <div
            class="row"
            role="button"
            tabindex="0"
            onclick={() => toggle(r.loader_md5)}
            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(r.loader_md5); } }}
          >
            <div class="vol-cell">
              <div class="vol-bar"><div class="vol-fill" style="width: {barPct}%"></div></div>
            </div>
            <span class="chev" class:open={isOpen}><CaretDown size={14} weight="regular" /></span>
            <span class="mono md5">{shortMd5(r.loader_md5)}</span>
            <button type="button" class="icon-btn" title="Copy full MD5" onclick={(e) => { e.stopPropagation(); copy(r.loader_md5); }}>
              <Copy size={11} weight="regular" />
            </button>
            {#if r.family_slug}
              <span class="fam-chip">{r.family_slug.toUpperCase()}</span>
            {:else}
              <span class="fam-dash">-</span>
            {/if}
            <span class="vic-count">{fmt(r.victim_count)} victims</span>
            <span class="spacer"></span>
            <span class="bypass-summary">
              <span class="bp-label">top bypass:</span>
              {#if r.top_bypass_av_name && r.top_bypass_rate > 0}
                <span class="bp-av">{r.top_bypass_av_name}</span>
                <span class="bp-rate {bypassColour(r.top_bypass_rate)}">{(r.top_bypass_rate * 100).toFixed(1)}%</span>
              {:else}
                <span class="bp-none">none detected</span>
              {/if}
            </span>
          </div>

          {#if isOpen}
            <div class="expand">
              <div class="stat-grid">
                <div class="stat">
                  <div class="stat-label">LOADER MD5</div>
                  <div class="stat-value mono md5-full">{r.loader_md5}</div>
                </div>
                <div class="stat">
                  <div class="stat-label">ARCHIVES</div>
                  <div class="stat-value">{fmt(r.archive_count)}</div>
                </div>
                <div class="stat">
                  <div class="stat-label">% OF DOMAIN</div>
                  <div class="stat-value">{pctStr(r.victim_count, samplesCtx.domain_total_victims)}</div>
                </div>
                <div class="stat">
                  <div class="stat-label">FIRST SEEN</div>
                  <div class="stat-value">{relTime(r.first_seen_at)}</div>
                </div>
                <div class="stat">
                  <div class="stat-label">LAST SEEN</div>
                  <div class="stat-value">{relTime(r.last_seen_at)}</div>
                </div>
              </div>

              {#if loading}
                <div class="detail-loading">Loading loader paths and AV breakdown...</div>
              {:else if detail}
                <div class="detail-section">
                  <div class="section-label">LOADER PATHS <span class="label-sub">TOP {detail.loader_paths.length}</span></div>
                  {#if detail.loader_paths.length === 0}
                    <div class="no-paths">No payload_path captured for this sample.</div>
                  {:else}
                    <div class="path-list">
                      {#each detail.loader_paths as p (p.path)}
                        <div class="path-row">
                          <span class="mono path-text">{p.path}</span>
                          <button type="button" class="icon-btn" title="Copy path" onclick={() => copy(p.path)}>
                            <Copy size={11} weight="regular" />
                          </button>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>

                {#if detail.av_breakdown.length > 0}
                  <div class="detail-section">
                    <div class="section-label">AV BYPASS <span class="label-sub">SORTED BY RATE</span></div>
                    <div class="av-list">
                      {#each detail.av_breakdown as a (a.av_name)}
                        {@const rate = a.total_count > 0 ? a.active_count / a.total_count : 0}
                        <div class="av-row">
                          <span class="av-name">{a.av_name}</span>
                          <span class="av-mid">{fmt(a.active_count)} of {fmt(a.total_count)} active at infection</span>
                          <div class="av-bar">
                            <div class="av-fill {bypassColour(rate)}" style="width: {rate * 100}%"></div>
                          </div>
                          <span class="av-rate mono {bypassColour(rate)}">{(rate * 100).toFixed(1)}%</span>
                        </div>
                      {/each}
                    </div>
                  </div>
                {/if}
              {/if}
            </div>
          {/if}
        </div>
      {/each}

      {#if nullSampleCount > 0}
        <div class="sample null-sample">
          <div class="row row-null">
            <div class="vol-cell"><div class="vol-bar"><div class="vol-fill null-fill"></div></div></div>
            <span class="chev"><CaretDown size={14} weight="regular" /></span>
            <span class="null-text">no sample</span>
            <span class="fam-dash">-</span>
            <span class="vic-count">{fmt(nullSampleCount)} victims</span>
            <span class="spacer"></span>
            <span class="no-meta">
              <Info size={11} weight="regular" />
              no loader metadata . {pctStr(nullSampleCount, samplesCtx.domain_total_victims)} of domain
            </span>
          </div>
        </div>
      {/if}
    </div>

    <div class="meta">Showing {fmt(displayLimit)} of {fmt(displayLimit)}</div>
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

  /* Samples: individual row CARDS stacked with a shared hairline, not a
     table. Each row is its own clickable surface with an expansion area
     that slots under it, unbreaking the table-row-height constraint. */
  .samples { display: flex; flex-direction: column; gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
  .sample { background: var(--surface); }
  .sample.open { background: var(--panel); }

  .row {
    display: flex; align-items: center; gap: 14px; padding: 12px 16px; width: 100%;
    cursor: pointer; color: inherit; outline: none; user-select: none;
  }
  .row:hover { background: rgba(255,255,255,0.015); }
  .row:focus-visible { box-shadow: inset 0 0 0 1px var(--accent-fill-strong); }

  .vol-cell { width: 96px; flex-shrink: 0; }
  .vol-bar { height: 2px; background: rgba(255,255,255,0.05); border-radius: 1px; overflow: hidden; }
  .vol-fill { height: 100%; background: var(--accent-text); border-radius: 1px; }
  .null-fill { width: 60%; background: var(--text-faint); }

  .chev { color: var(--text-muted); display: inline-flex; transition: transform 150ms ease; transform: rotate(-90deg); }
  .chev.open { transform: rotate(0deg); color: var(--text-body); }

  .mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  .md5 { color: var(--text); font-weight: var(--fw-medium); }

  .icon-btn {
    appearance: none; background: transparent; border: 1px solid transparent; border-radius: 3px;
    padding: 2px 4px; cursor: pointer; color: var(--text-faint); display: inline-flex; align-items: center;
  }
  .icon-btn:hover { background: var(--accent-fill); color: var(--accent-text); border-color: var(--accent-fill-strong); }

  /* Family chip: purple accent, mono uppercase. Stealc / Lumma / Redline
     / Vidar / etc. The dash variant renders for null-sample row + rows
     whose verdict table lookup returned empty. */
  .fam-chip {
    display: inline-flex; align-items: center;
    padding: 2px 8px; border: 1px solid var(--accent-fill-strong); border-radius: 10px;
    background: var(--accent-fill); color: var(--accent-text);
    font-family: var(--font-mono); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    text-transform: uppercase; letter-spacing: 0.06em;
  }
  .fam-dash {
    display: inline-flex; align-items: center;
    padding: 2px 10px; border: 1px dashed var(--border-strong); border-radius: 10px;
    color: var(--text-faint);
    font-family: var(--font-mono); font-size: var(--fs-12);
  }

  .vic-count { color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); }
  .spacer { flex: 1; }

  /* Top-bypass summary on the collapsed row. Rate value coloured by band;
     label stays muted so the number pops. */
  .bypass-summary { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-12); }
  .bp-label { color: var(--text-faint); }
  .bp-av { color: var(--text-body); }
  .bp-rate { font-family: var(--font-mono); font-size: var(--fs-13); font-weight: var(--fw-semibold); margin-left: 4px; }
  .bp-none {
    font-family: var(--font-sans); font-size: var(--fs-12); font-style: italic;
    color: var(--text-faint);
  }
  .bp-high { color: var(--red-text); }
  .bp-mid { color: var(--warn-text); }
  .bp-low { color: var(--text-ok, #5bbf80); }

  /* Null-sample row: muted everything, italic label, no bypass summary. */
  .null-sample .row { cursor: default; }
  .null-sample .row:hover { background: transparent; }
  .null-text { font-style: italic; color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); }
  .no-meta {
    display: inline-flex; align-items: center; gap: 6px;
    color: var(--text-faint); font-family: var(--font-sans); font-size: var(--fs-12); font-style: italic;
  }

  /* Expanded panel: stat grid, loader paths, AV bypass. Each section
     has its own uppercase label with an optional sub-label. */
  .expand { padding: 4px 16px 18px; display: flex; flex-direction: column; gap: 14px; }
  .stat-grid {
    display: grid;
    grid-template-columns: minmax(260px, 2fr) repeat(4, 1fr);
    gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: 4px; overflow: hidden;
  }
  .stat { background: var(--surface); padding: 10px 14px; display: flex; flex-direction: column; gap: 4px; }
  .stat-label {
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-medium);
    color: var(--text-muted); text-transform: uppercase; letter-spacing: var(--tracking-label);
  }
  .stat-value { color: var(--text); font-family: var(--font-sans); font-size: var(--fs-13); }
  .md5-full { font-size: var(--fs-12); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-body); }

  .detail-section { display: flex; flex-direction: column; gap: 8px; }
  .section-label {
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-medium);
    color: var(--text-muted); text-transform: uppercase; letter-spacing: var(--tracking-label);
  }
  .label-sub { color: var(--text-faint); font-weight: var(--fw-normal); margin-left: 6px; }

  .path-list { display: flex; flex-direction: column; gap: 6px; }
  .path-row {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px; border: 1px solid var(--border); border-radius: 3px;
    background: var(--panel);
  }
  .path-text { color: var(--text-body); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .no-paths {
    padding: 10px 14px; border: 1px dashed var(--border); border-radius: 3px;
    color: var(--text-faint); font-family: var(--font-sans); font-size: var(--fs-12); font-style: italic;
  }

  .av-list { display: flex; flex-direction: column; gap: 4px; }
  .av-row {
    display: grid; grid-template-columns: 1fr auto 140px auto; align-items: center; gap: 14px;
    padding: 8px 12px; border-bottom: 1px solid var(--border);
  }
  .av-row:last-child { border-bottom: 0; }
  .av-name { color: var(--text); font-family: var(--font-sans); font-size: var(--fs-13); }
  .av-mid { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-12); text-align: right; }
  .av-bar { height: 4px; background: rgba(255,255,255,0.05); border-radius: 2px; overflow: hidden; }
  .av-fill { height: 100%; border-radius: 2px; }
  .av-fill.bp-high { background: var(--red-text); }
  .av-fill.bp-mid { background: var(--warn-text); }
  .av-fill.bp-low { background: var(--text-ok, #5bbf80); }
  .av-rate { font-size: var(--fs-13); font-weight: var(--fw-semibold); text-align: right; min-width: 50px; }

  .detail-loading {
    padding: 14px; color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-12); font-style: italic;
    text-align: center;
  }

  .meta { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); padding-top: 4px; }
</style>
