<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { apiGet } from '$lib/api.js';
  import { incidentLabelName } from '$lib/data.js';

  // Thread list for a forum category (GroupKind.FORUM_CATEGORY). Each thread
  // opens to its posts. Only forums have this layer; chats skip straight to messages.
  // Each thread carries its OP-anchored rollup (date + victim country + incident labels)
  // so the list is scannable and filterable without opening the thread. A search box
  // flips this to a cross-thread body search (GET .../search?q=), scoped to THIS category.
  let threads = $state([]);
  let error = $state(null);
  let loaded = $state(false);
  let search = $state('');
  let hits = $state([]); // cross-thread search results (each carries its thread)
  let total = $state(null);
  let searching = $state(false);
  let searchTimer;
  const searchMode = $derived(search.trim().length > 0);

  // Sort + filters (server-side via ?sort=&country=&label=). Option universe is captured
  // from the first unfiltered load so checkboxes don't vanish as you filter.
  let sort = $state('date'); // 'date' (OP post time) | 'recent' (last observed)
  let selectedCountries = $state(new Set());
  let selectedLabels = $state(new Set());
  let countryOpts = $state([]);
  let labelOpts = $state([]);

  async function load() {
    const params = new URLSearchParams({ limit: '200', sort });
    for (const c of selectedCountries) params.append('country', c);
    for (const l of selectedLabels) params.append('label', l);
    try {
      const p = await apiGet(`/v1/groups/${$page.params.id}/threads?${params}`, { auth: true });
      threads = p.items ?? [];
      error = null;
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  }

  onMount(async () => {
    await load();
    // Capture the filter universe from the initial (unfiltered) load.
    countryOpts = [...new Set(threads.map((t) => t.victim_country).filter(Boolean))].sort();
    labelOpts = [...new Set(threads.flatMap((t) => t.incident_labels ?? []))].sort();
  });

  function toggleCountry(c) {
    selectedCountries.has(c) ? selectedCountries.delete(c) : selectedCountries.add(c);
    selectedCountries = new Set(selectedCountries);
    load();
  }
  function toggleLabel(l) {
    selectedLabels.has(l) ? selectedLabels.delete(l) : selectedLabels.add(l);
    selectedLabels = new Set(selectedLabels);
    load();
  }
  function setSort(s) {
    sort = s;
    load();
  }

  async function runSearch() {
    const q = search.trim();
    if (!q) {
      hits = [];
      total = null;
      return;
    }
    searching = true;
    error = null;
    try {
      const params = new URLSearchParams({ q, limit: '200', include_total: '1' });
      const p = await apiGet(`/v1/groups/${$page.params.id}/search?${params}`, { auth: true });
      hits = p.items ?? [];
      total = p.estimated_total ?? null;
    } catch (e) {
      error = e.message;
    }
    searching = false;
  }

  // Debounce keystrokes: one request 250ms after the operator stops typing.
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 250);
  }

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '—');
  const snippet = (b) => (b ?? '').replace(/\s+/g, ' ').slice(0, 140);

  // ISO alpha-2 -> full country name via the browser's built-in region names
  // (CL -> Chile), so filters read premium. Falls back to the code on anything odd.
  const _regionNames =
    typeof Intl !== 'undefined' && Intl.DisplayNames
      ? new Intl.DisplayNames(['en'], { type: 'region' })
      : null;
  function countryName(code) {
    if (!code) return code;
    try {
      return _regionNames?.of(code) ?? code;
    } catch {
      return code;
    }
  }

  // Close any open filter popover when clicking outside it (matches the incidents page).
  $effect(() => {
    function onDocClick(e) {
      for (const d of document.querySelectorAll('details.pop[open]')) {
        if (!d.contains(e.target)) d.open = false;
      }
    }
    document.addEventListener('click', onDocClick);
    return () => document.removeEventListener('click', onDocClick);
  });
</script>

<main>
  <div class="head">
    <div class="crumb">
      <a class="slug-link" href="/reader">reader</a><span class="sep">/</span><span class="slug">category</span>
    </div>
    <h1>Threads</h1>
    <div class="searchrow">
      <input
        class="search"
        type="search"
        placeholder="Search every thread in this category…"
        bind:value={search}
        oninput={onSearch}
        aria-label="Search message bodies across this category's threads" />
      {#if searchMode && !searching}
        <span class="scount">
          {hits.length}{#if total != null && total > hits.length}<span class="oftotal"> / {total}</span>{/if}
          match{(total ?? hits.length) === 1 ? '' : 'es'}
        </span>
      {/if}
    </div>
  </div>

  <div class="body">
    {#if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if searchMode}
      {#if searching}
        <p class="pnote">Searching…</p>
      {:else if !hits.length}
        <p class="pnote">No posts in this category match “{search.trim()}”.</p>
      {:else}
        <ul class="rows">
          {#each hits as h}
            <li>
              <a class="row" href={`/reader/group/${h.thread_group_id}`}>
                <span class="title">{snippet(h.body)}</span>
                <span class="meta">in {h.thread_title || h.thread_group_id.slice(0, 8)} · {h.author_display || 'unknown'} · {fmt(h.ts)}</span>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    {:else if !loaded}
      <p class="pnote">Loading…</p>
    {:else}
      {#if countryOpts.length || labelOpts.length}
        <div class="filterbar">
          <div class="fgroup">
            <span class="flabel">sort</span>
            <button class="chip" class:on={sort === 'date'} onclick={() => setSort('date')}>date</button>
            <button class="chip" class:on={sort === 'recent'} onclick={() => setSort('recent')}>recent</button>
          </div>

          {#if countryOpts.length}
            <details class="pop">
              <summary>{selectedCountries.size ? `${selectedCountries.size} countr${selectedCountries.size > 1 ? 'ies' : 'y'}` : 'Country'}</summary>
              <div class="pmenu">
                {#each countryOpts as c}
                  <label class="popt"><input type="checkbox" checked={selectedCountries.has(c)} onchange={() => toggleCountry(c)} /> {countryName(c)}</label>
                {/each}
              </div>
            </details>
          {/if}

          {#if labelOpts.length}
            <details class="pop">
              <summary>{selectedLabels.size ? `${selectedLabels.size} incident${selectedLabels.size > 1 ? 's' : ''}` : 'Incident'}</summary>
              <div class="pmenu">
                {#each labelOpts as l}
                  <label class="popt"><input type="checkbox" checked={selectedLabels.has(l)} onchange={() => toggleLabel(l)} /> {incidentLabelName(l)}</label>
                {/each}
              </div>
            </details>
          {/if}
        </div>
      {/if}
      {#if !threads.length}
        <p class="pnote">No threads match. The collector fills these as it crawls (paced); geo/incident tags fill in as the workers process each thread's first post.</p>
      {:else}
        <ul class="rows">
          {#each threads as t}
            <li>
              <a class="row" href={`/reader/group/${t.group_id}`}>
                <span class="title">
                  {#if t.victim_country}<span class="badge country" title={countryName(t.victim_country)}>{t.victim_country}</span>{/if}
                  {#each t.incident_labels ?? [] as l}<span class="badge incident">{incidentLabelName(l)}</span>{/each}
                  {t.title || t.platform_groupid}
                </span>
                <span class="meta">tid {t.platform_groupid} · {fmt(t.thread_date ?? t.last_observed_at)}</span>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { padding: 20px 24px 0; }
  .crumb { display: flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .slug-link { color: var(--text-secondary); text-decoration: none; }
  .slug-link:hover { color: var(--accent); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); }
  .searchrow { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
  .search { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; min-width: 280px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .scount { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); white-space: nowrap; }
  .oftotal { color: var(--text-muted); }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 12px 24px 24px; }
  .rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .row { display: flex; flex-direction: column; gap: 2px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; text-decoration: none; }
  .row:hover { border-color: var(--accent); }
  .title { color: var(--text-body); font-size: var(--fs-14); word-break: break-word; }
  .meta { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .filterbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
  .fgroup { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); margin-right: 2px; }
  .chip { background: var(--surface); border: 1px solid var(--border-strong); border-radius: 3px; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-11); padding: 2px 8px; cursor: pointer; }
  .chip:hover { border-color: var(--accent); }
  .chip.on { background: var(--accent); border-color: var(--accent); color: var(--black); }
  .pop { position: relative; }
  .pop > summary { list-style: none; cursor: pointer; user-select: none; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); padding: 6px 12px; white-space: nowrap; }
  .pop > summary::-webkit-details-marker { display: none; }
  .pop[open] > summary { border-color: var(--accent); }
  .pmenu { position: absolute; z-index: 40; top: calc(100% + 4px); left: 0; min-width: 200px; max-height: 320px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; padding: 8px; background: var(--panel); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: var(--shadow-2, 0 8px 24px rgba(0,0,0,0.4)); }
  .popt { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: var(--radius); font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); cursor: pointer; white-space: nowrap; }
  .popt:hover { background: var(--panel-2); }
  .popt input { accent-color: var(--accent); }
  .badge { font-family: var(--font-sans); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); border: 1px solid var(--text-faint); color: var(--text-body); border-radius: 3px; padding: 0 5px; margin-right: 4px; }
  .badge.incident { color: var(--red-text); border-color: var(--red-text); }
  .badge.country { color: var(--text-body); border-color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
</style>
