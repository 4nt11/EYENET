<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { boardOf, prepare, onGuardedClick } from '$lib/linkguard.js';
  import { apiGet } from '$lib/api.js';
  import { incidentLabelName, incidentTone } from '$lib/data.js';
  import RelabelEditor from '$lib/components/RelabelEditor.svelte';
  import DossierLayout from '$lib/components/DossierLayout.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import CaseAddModal from '$lib/components/CaseAddModal.svelte';

  // Two-pane reader for a forum category: threads in the rail (each carries its
  // OP-anchored rollup — victim country + incident labels + date, so the list is
  // scannable and filterable), the selected thread's posts in the dossier pane.
  // Filters (country / incident checkbox dropdowns + sort) live top-right, matching
  // the incidents page. A search box flips the pane to a cross-thread body search.
  let threads = $state([]);
  let error = $state(null);
  let loaded = $state(false);
  let selectedId = $state(null);

  // Sort + filters (server-side via ?sort=&country=&label=). Option universe is
  // captured from the first unfiltered load so checkboxes don't vanish as you filter.
  let sort = $state('date'); // 'date' (OP post time) | 'recent' (last observed)
  let selectedCountries = $state(new Set());
  let selectedLabels = $state(new Set());
  let countryOpts = $state([]);
  let labelOpts = $state([]);
  let threadTotal = $state(null); // real total for the current filter (not the page cap)

  // Detail pane: the selected thread's posts.
  let detailMsgs = $state([]);
  let detailLoaded = $state(false);
  let caseModalPost = $state(null); // {id, actor_id, author, threadTitle} or null

  // Cross-thread body search (scoped to this category).
  let search = $state('');
  let hits = $state([]);
  let total = $state(null);
  let searching = $state(false);
  let searchTimer;
  const searchMode = $derived(search.trim().length > 0);
  const selectedThread = $derived(threads.find((t) => t.group_id === selectedId) ?? null);

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

  const fmt = (ts) => (ts ? new Date(ts).toLocaleString() : '—');

  async function load() {
    const params = new URLSearchParams({ limit: '200', sort, include_total: '1' });
    for (const c of selectedCountries) params.append('country', c);
    for (const l of selectedLabels) params.append('label', l);
    try {
      const p = await apiGet(`/v1/groups/${$page.params.id}/threads?${params}`, { auth: true });
      threads = p.items ?? [];
      threadTotal = p.estimated_total ?? null;
      error = null;
    } catch (e) {
      error = e.message;
    }
    loaded = true;
  }

  onMount(async () => {
    await load();
    countryOpts = [...new Set(threads.map((t) => t.victim_country).filter(Boolean))].sort();
    labelOpts = [...new Set(threads.flatMap((t) => t.incident_labels ?? []))].sort();
  });

  async function selectThread(id) {
    selectedId = id;
    detailLoaded = false;
    detailMsgs = [];
    try {
      const p = await apiGet(`/v1/groups/${id}/messages?limit=200`, { auth: true });
      detailMsgs = p.items ?? [];
    } catch (e) {
      error = e.message;
    }
    detailLoaded = true;
  }

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
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 250);
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

  const rowItems = $derived(
    threads.map((t) => ({
      id: t.group_id,
      primary: t.title || t.platform_groupid,
      secondary:
        (t.victim_country ? `[${t.victim_country}] ` : '') +
        ((t.incident_labels ?? []).map(incidentLabelName).join(' · ') || 'no incident') +
        ' · ' +
        fmt(t.thread_date ?? t.last_observed_at)
    }))
  );
</script>

<DossierLayout
  listLabel="Threads"
  items={rowItems}
  {selectedId}
  onSelect={selectThread}
  selected={!!selectedId || searchMode}>

  {#snippet title()}
    {#if searchMode}
      <span class="mid muted">Search</span>
    {:else if selectedThread}
      <span class="mid">{selectedThread.title || selectedThread.platform_groupid}</span>
    {:else}
      <span class="mid muted">Threads</span>
    {/if}
  {/snippet}

  {#snippet filters()}
    <span class="fcount">{threadTotal ?? threads.length}{#if threadTotal != null && threadTotal > threads.length}<span class="oftotal"> (showing {threads.length})</span>{/if} thread{(threadTotal ?? threads.length) === 1 ? '' : 's'}</span>
    <input
      class="search"
      type="search"
      placeholder="Search this category…"
      bind:value={search}
      oninput={onSearch}
      aria-label="Search message bodies across this category's threads" />

    <div class="fgroup">
      <span class="flabel">sort</span>
      <button class="chip" class:on={sort === 'date'} onclick={() => setSort('date')} title="When the thread's first post (OP) was posted">posted</button>
      <button class="chip" class:on={sort === 'recent'} onclick={() => setSort('recent')} title="When EYENET last ingested activity in this thread">last seen</button>
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
  {/snippet}

  {#snippet head()}
    {#if !searchMode && selectedThread}
      <div class="dhead">
        {#each selectedThread.incident_labels ?? [] as l}<Badge tone={incidentTone(l)}>{incidentLabelName(l)}</Badge>{/each}
        {#if selectedThread.victim_country}
          <span class="dmeta">victim {countryName(selectedThread.victim_country)}</span>
        {/if}
        <span class="dmeta">tid {selectedThread.platform_groupid} · {fmt(selectedThread.thread_date ?? selectedThread.last_observed_at)}</span>
        <a class="openlink" href={`/reader/group/${selectedThread.group_id}`}>open full thread →</a>
      </div>
    {/if}
  {/snippet}

  {#snippet body()}
    {#if error}
      <p class="pnote err">Could not load: {error}</p>
    {:else if searchMode}
      {#if searching}
        <p class="pnote">Searching…</p>
      {:else if !hits.length}
        <p class="pnote">No posts in this category match “{search.trim()}”.</p>
      {:else}
        <p class="pnote">{hits.length}{#if total != null && total > hits.length} / {total}{/if} match{(total ?? hits.length) === 1 ? '' : 'es'}</p>
        <ul class="posts">
          {#each hits as h}
            <li class="post">
              <a class="prow" href={`/reader/group/${h.thread_group_id}`}>
                <span class="pauthor">in {h.thread_title || h.thread_group_id.slice(0, 8)}</span>
                <span class="pbody">{(h.body ?? '').replace(/\s+/g, ' ').slice(0, 200)}</span>
                <span class="pts">{h.author_display || 'unknown'} · {fmt(h.ts)}</span>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    {:else if !detailLoaded}
      <p class="pnote">Loading posts…</p>
    {:else if !detailMsgs.length}
      <p class="pnote">No posts stored for this thread yet.</p>
    {:else}
      <ul class="posts" onclick={onGuardedClick}>
        {#each detailMsgs as m}
          <li class="post">
            <div class="pmeta">
              <span class="pauthor">{m.author_display || m.author_username || 'unknown'}</span>
              <span class="pts">{fmt(m.ts)}</span>
              {#if m.victim_country}<span class="pts" title={countryName(m.victim_country)}>victim {m.victim_country}</span>{/if}
              <button
                class="casebtn"
                title="Add to a case"
                onclick={() => (caseModalPost = { id: m.id, actor_id: m.actor_id, author: m.author_display || m.author_username, threadTitle: selectedThread?.title })}>+ case</button>
            </div>
            <RelabelEditor message={m} />
            {#if m.body_html}
              <div class="pbody">{@html prepare(m.body_html, boardOf(m.evidence_ref))}</div>
            {:else}
              <div class="pbody plain">{m.body}</div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/snippet}

  {#snippet empty()}
    {#if !loaded}
      <p class="pnote">Loading…</p>
    {:else if !threads.length}
      <p class="pnote">No threads discovered in this category yet. The collector fills these as it crawls (paced); geo/incident tags fill in as the workers process each thread's first post.</p>
    {:else}
      <p class="pnote">Select a thread to read its posts, or search across the category.</p>
    {/if}
  {/snippet}
</DossierLayout>

{#if caseModalPost}
  <CaseAddModal post={caseModalPost} onClose={() => (caseModalPost = null)} />
{/if}

<style>
  .mid { font-size: var(--fs-16); color: var(--text-body); min-width: 0; overflow-wrap: anywhere; }
  .mid.muted { color: var(--text-faint); }
  .oftotal { color: var(--text-muted); }
  .search { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 5px 10px; min-width: 200px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .fgroup { display: flex; align-items: center; gap: 4px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); margin-right: 2px; }
  .chip { appearance: none; padding: 3px 9px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); cursor: pointer; }
  .chip:hover { background: var(--panel-2); }
  .chip.on { background: var(--accent-fill); border-color: var(--accent); color: var(--text); }

  .pop { position: relative; }
  .pop > summary { list-style: none; cursor: pointer; user-select: none; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); padding: 6px 12px; white-space: nowrap; }
  .pop > summary::-webkit-details-marker { display: none; }
  .pop[open] > summary { border-color: var(--accent); }
  .pmenu { position: absolute; z-index: 40; top: calc(100% + 4px); right: 0; min-width: 200px; max-height: 320px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; padding: 8px; background: var(--panel); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: var(--shadow-2, 0 8px 24px rgba(0,0,0,0.4)); }
  .popt { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: var(--radius); font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); cursor: pointer; white-space: nowrap; }
  .popt:hover { background: var(--panel-2); }
  .popt input { accent-color: var(--accent); }

  .dhead { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; }
  .dmeta { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .openlink { margin-left: auto; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent); text-decoration: none; }
  .openlink:hover { text-decoration: underline; }

  .posts { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  .post { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 14px; }
  .pmeta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 6px; }
  .prow { display: flex; flex-direction: column; gap: 3px; text-decoration: none; }
  .prow:hover { color: var(--accent); }
  .pauthor { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-secondary); }
  .pts { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .pbody { color: var(--text-body); font-size: var(--fs-13); word-break: break-word; overflow-wrap: anywhere; }
  .pbody.plain { white-space: pre-wrap; font-family: var(--font-mono); font-size: var(--fs-12); }
  .pbody :global(img) { max-width: 100%; height: auto; }
  /* Links come from sanitized {@html} (defanged by linkguard), so they need
     :global to be reachable. armed1/armed2 mark the triple-click open states. */
  .pbody :global(a) { color: var(--link); text-decoration: underline; overflow-wrap: anywhere; cursor: pointer; }
  .pbody :global(a:hover) { color: var(--link-hover); }
  .pbody :global(a.armed1) { color: var(--accent-text); font-family: var(--font-mono); }
  .pbody :global(a.armed2) { color: var(--red-text); font-family: var(--font-mono); font-weight: 600; }
  .casebtn { appearance: none; margin-left: auto; padding: 2px 8px; border: 1px solid var(--border-strong); border-radius: 3px; background: transparent; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-10); text-transform: uppercase; letter-spacing: var(--tracking-label); cursor: pointer; }
  .casebtn:hover { border-color: var(--accent); color: var(--accent); }

  .pnote { margin: 0; padding: 8px 2px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
</style>
