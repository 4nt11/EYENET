<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Button from '$lib/components/Button.svelte';
  import { statsCtx, loadStealerStats, searchCtx, searchStealer } from '$lib/stealer.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  // Bar width % relative to the biggest bucket in the set.
  const bars = (buckets) => {
    const max = Math.max(1, ...(buckets ?? []).map((b) => b.count));
    return (buckets ?? []).map((b) => ({ ...b, pct: Math.round((b.count / max) * 100) }));
  };
  // Cap the two side-by-side panels to the same row count so they're equal height
  // (symmetry) — the long tail isn't worth the dead space.
  const PANEL_ROWS = 12;
  const byTld = $derived(bars((statsCtx.stats?.by_tld ?? []).slice(0, PANEL_ROWS)));
  const byScheme = $derived(bars((statsCtx.stats?.by_scheme ?? []).slice(0, PANEL_ROWS)));
  const topHosts = $derived(bars(statsCtx.stats?.top_hosts));

  let host = $state('');
  const runSearch = () => searchStealer(host);

  const COLUMNS = [
    { key: 'host', header: 'Host', mono: true, width: '260px' },
    { key: 'login', header: 'Login', mono: true },
    { key: 'password', header: 'Password', mono: true },
    { key: 'scheme', header: 'Scheme', mono: true, width: '90px' },
    { key: 'tld', header: 'TLD', mono: true, width: '70px' }
  ];

  onMount(loadStealerStats);
</script>

<main>
  <div class="head">
    <SectionHeader group="Stealer" slug="stealer" title="ULP corpus" />
  </div>

  {#if statsCtx.denied}
    <p class="note">This surface needs a <code>read:stealer</code> clearance grant. Ask an admin to grant it (it's time-bounded).</p>
  {:else if statsCtx.error}
    <p class="note err">{statsCtx.error}</p>
  {:else if !statsCtx.loaded}
    <p class="note">Loading corpus…</p>
  {:else if statsCtx.stats}
    {@const s = statsCtx.stats}
    <section class="search">
      <div class="search-bar">
        <input class="in" type="search" placeholder="Search credentials by host (substring, e.g. google.com)…"
          bind:value={host} onkeydown={(e) => e.key === 'Enter' && runSearch()} aria-label="Search credentials by host" />
        <Button variant="primary" size="sm" disabled={searchCtx.loading} onclick={runSearch}>Search</Button>
      </div>
      {#if searchCtx.error}
        <p class="note err">{searchCtx.error}</p>
      {:else if searchCtx.loading}
        <p class="note">Searching…</p>
      {:else if searchCtx.ran}
        {#if searchCtx.items.length}
          <p class="count">{searchCtx.items.length} result{searchCtx.items.length === 1 ? '' : 's'}{searchCtx.items.length === 200 ? ' (capped)' : ''}</p>
          <div class="table-scroll">
            <DataTable rowKey="host" columns={COLUMNS} rows={searchCtx.items} stickyHead stickyTop="0" />
          </div>
        {:else}
          <p class="note">No credentials match.</p>
        {/if}
      {/if}
    </section>

    <div class="overview-label">Corpus overview</div>
    <section class="tiles">
      <StatTile label="Total credentials" value={fmt(s.total_creds)} tone="accent" />
      <StatTile label="Unique (host·login·pass)" value={fmt(s.unique_creds)} />
      <StatTile label="Distinct hosts" value={fmt(s.distinct_hosts)} />
    </section>

    <section class="charts">
      <div class="chart">
        <h3>By TLD <span class="hint">(of the service host)</span></h3>
        {#each byTld as b}
          <div class="row"><span class="k">{b.key}</span><span class="track"><span class="fill" style="width:{b.pct}%"></span></span><span class="n">{fmt(b.count)}</span></div>
        {/each}
        {#if !byTld.length}<p class="hint">no ccTLD signal</p>{/if}
      </div>
      <div class="chart">
        <h3>By scheme</h3>
        {#each byScheme as b}
          <div class="row"><span class="k">{b.key || '—'}</span><span class="track"><span class="fill alt" style="width:{b.pct}%"></span></span><span class="n">{fmt(b.count)}</span></div>
        {/each}
      </div>
      <div class="chart wide">
        <h3>Top targeted hosts</h3>
        {#each topHosts as b}
          <div class="row"><span class="k host">{b.key}</span><span class="track"><span class="fill" style="width:{b.pct}%"></span></span><span class="n">{fmt(b.count)}</span></div>
        {/each}
      </div>
    </section>
  {/if}
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: auto; background: var(--black); padding-bottom: 24px; }
  .head { padding-right: 20px; }
  .note { margin: 16px 20px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .note.err { color: var(--red-text); }
  .note code { background: var(--panel); padding: 1px 5px; border-radius: 4px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; padding: 0 20px 4px; }
  /* Two equal panels on top (TLD | scheme), full-width hosts below. Explicit 1fr 1fr
     (not auto-fit) so they fill the row 50/50 with no stranded empty column. */
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px 20px; align-items: start; }
  .chart { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 12px 14px; min-width: 0; }
  .chart.wide { grid-column: 1 / -1; }
  @media (max-width: 760px) { .charts { grid-template-columns: 1fr; } }
  .chart h3 { margin: 0 0 10px; font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .chart h3 .hint { text-transform: none; font-weight: var(--fw-regular); color: var(--text-faint); }
  .row { display: grid; grid-template-columns: 120px 1fr 72px; align-items: center; gap: 10px; padding: 3px 0; }
  .k { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .k.host { font-size: var(--fs-11); }
  .track { height: 8px; background: var(--surface); border-radius: 4px; overflow: hidden; }
  .fill { display: block; height: 100%; background: var(--accent); border-radius: 4px; }
  .fill.alt { background: var(--accent-text); opacity: 0.7; }
  .n { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); text-align: right; }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  /* Search is the headline feature — sits at the top, right under the header. */
  .search { padding: 16px 20px 4px; display: flex; flex-direction: column; gap: 10px; }
  .search-bar { display: flex; gap: 8px; align-items: center; }
  .overview-label { padding: 12px 20px 0; font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .in { flex: 1 1 320px; min-width: 200px; box-sizing: border-box; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-14); padding: 9px 12px; }
  .in:focus { outline: none; border-color: var(--accent); }
  .count { margin: 0; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .table-scroll { max-height: 55vh; overflow: auto; }
</style>
