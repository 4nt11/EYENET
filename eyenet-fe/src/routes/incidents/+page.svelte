<script>
  import { onMount } from 'svelte';
  import DossierLayout from '$lib/components/DossierLayout.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Button from '$lib/components/Button.svelte';
  import { incidentTone, incidentLabelName, INCIDENT_LABELS, INCIDENT_LABEL_GROUPS } from '$lib/data.js';
  import {
    incidentCtx,
    incidentEdit,
    loadIncidents,
    loadMoreIncidents,
    loadIncidentGroups,
    loadIncidentSources,
    loadIncidentCountries,
    relabelIncident
  } from '$lib/incident.svelte.js';

  let selectedLabels = $state(new Set()); // OR include-filter over taxonomy leaves
  let selectedGroups = $state(new Set()); // group ids to show (empty = all groups)
  let selectedSources = $state(new Set()); // source ids to show (empty = all sources)
  let selectedCountries = $state(new Set()); // ISO alpha-2 victim countries to show (empty = all)
  let search = $state('');
  let searchTimer;

  let selectedId = $state(null);
  let sel = $derived(incidentCtx.list.find((x) => x.id === selectedId) ?? incidentCtx.list[0] ?? null);

  onMount(() => {
    loadIncidents();
    loadIncidentGroups(); // the full group set for the group filter (not the feed window)
    loadIncidentSources(); // the source-level filter (a whole forum in one option)
    loadIncidentCountries(); // the victim-country filter (?q= never matched the geo verdict)
  });

  // Close any open filter popover when clicking outside it.
  $effect(() => {
    function onDocClick(e) {
      for (const d of document.querySelectorAll('details.pop[open]')) {
        if (!d.contains(e.target)) d.open = false;
      }
    }
    document.addEventListener('click', onDocClick);
    return () => document.removeEventListener('click', onDocClick);
  });

  // The group popover lists the full server set (noisiest first), so groups outside the
  // current 200-row window are still mutable.
  // Scope the group list to the selected source(s): picking "Darkforums" should
  // narrow Groups to its threads, not still list Telegram chats. No source selected
  // = all groups.
  const groupOpts = $derived(
    selectedSources.size
      ? incidentCtx.groups.filter((g) => selectedSources.has(g.sourceId))
      : incidentCtx.groups
  );
  const sourceOpts = $derived(incidentCtx.sources);
  const countryOpts = $derived(incidentCtx.countries);

  function applyFilter() {
    selectedId = null;
    loadIncidents(
      [...selectedLabels],
      search.trim(),
      [...selectedGroups],
      [...selectedSources],
      [...selectedCountries]
    );
  }

  function toggleLabel(l) {
    const n = new Set(selectedLabels);
    n.has(l) ? n.delete(l) : n.add(l);
    selectedLabels = n;
    applyFilter();
  }

  function toggleGroup(id) {
    const n = new Set(selectedGroups);
    n.has(id) ? n.delete(id) : n.add(id);
    selectedGroups = n;
    applyFilter();
  }

  function toggleSource(id) {
    const n = new Set(selectedSources);
    n.has(id) ? n.delete(id) : n.add(id);
    selectedSources = n;
    applyFilter();
  }

  function toggleCountry(code) {
    const n = new Set(selectedCountries);
    n.has(code) ? n.delete(code) : n.add(code);
    selectedCountries = n;
    applyFilter();
  }

  // Debounce keystrokes: one request 250ms after the operator stops typing.
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilter, 250);
  }

  // Relabel editor: a local draft label-set + reason, seeded from the current
  // correction (or the model's labels if none), reset whenever the selection moves.
  const REASON_PRESETS = ['False positive', 'Incorrectly tagged', 'Missing label', 'Partially correct'];
  let editing = $state(false);
  let draft = $state(new Set());
  let reason = $state('');
  let customReason = $state(false); // true = free-text; false = a preset is (or will be) chosen
  $effect(() => {
    // depend on sel.id so switching rows re-seeds the draft
    const base = sel?.correctedLabels ?? sel?.labels ?? [];
    draft = new Set(base);
    reason = '';
    customReason = false;
    editing = false;
    void sel?.id;
  });

  function toggle(label) {
    const next = new Set(draft);
    next.has(label) ? next.delete(label) : next.add(label);
    draft = next;
  }

  const canSave = $derived(reason.trim().length > 0 && !incidentEdit.submitting);

  async function save() {
    // head order, so the stored set reads consistently with the model output
    const labels = INCIDENT_LABELS.filter((l) => draft.has(l));
    const ok = await relabelIncident(sel.id, labels, reason.trim());
    if (ok) editing = false;
  }
</script>

<DossierLayout listLabel="Incidents"
  items={incidentCtx.list.map((x) => ({ id: x.id, primary: x.labels.map(incidentLabelName).join(' · ') || x.idShort, secondary: (x.victimCountry ? '[' + x.victimCountry + '] ' : '') + (x.group ? x.group + ' · ' : '') + ((x.body ?? '').slice(0, 56) || x.idShort) }))}
  selectedId={sel?.id} onSelect={(id) => (selectedId = id)}
  onLoadMore={loadMoreIncidents} hasMore={!!incidentCtx.nextCursor}
  selected={!!sel}>

  {#snippet title()}
    {#if sel}
      <span class="mid">message {sel.idShort}</span>
    {:else}
      <span class="mid muted">Incidents</span>
    {/if}
  {/snippet}

  {#snippet filters()}
    <div class="fcount">
      {incidentCtx.list.length}{#if incidentCtx.total != null && incidentCtx.total > incidentCtx.list.length}<span class="oftotal"> / {incidentCtx.total}</span>{/if}
      detection{(incidentCtx.total ?? incidentCtx.list.length) === 1 ? '' : 's'}
    </div>
    <input class="search" type="search" placeholder="Search message body…" bind:value={search} oninput={onSearch} aria-label="Search incident message bodies" />

    <details class="pop">
      <summary>{selectedLabels.size ? `${selectedLabels.size} label${selectedLabels.size > 1 ? 's' : ''}` : 'Labels'}</summary>
      <div class="pmenu">
        {#each INCIDENT_LABEL_GROUPS as grp (grp.name)}
          <span class="pgroup">{grp.name}</span>
          {#each grp.leaves as l (l)}
            <label class="popt"><input type="checkbox" checked={selectedLabels.has(l)} onchange={() => toggleLabel(l)} /> {incidentLabelName(l)}</label>
          {/each}
        {/each}
      </div>
    </details>

    <details class="pop">
      <summary>{selectedGroups.size ? `${selectedGroups.size} group${selectedGroups.size > 1 ? 's' : ''}` : 'Groups'}</summary>
      <div class="pmenu">
        <span class="phint">show only checked groups</span>
        {#if groupOpts.length === 0}<span class="pnone">no groups yet</span>{/if}
        {#each groupOpts as g (g.id)}
          <label class="popt">
            <input type="checkbox" checked={selectedGroups.has(g.id)} onchange={() => toggleGroup(g.id)} />
            <span class="ptitle">{g.title}</span>
            <span class="pcount">{g.count}</span>
          </label>
        {/each}
      </div>
    </details>

    <details class="pop">
      <summary>{selectedSources.size ? `${selectedSources.size} source${selectedSources.size > 1 ? 's' : ''}` : 'Sources'}</summary>
      <div class="pmenu">
        <span class="phint">show only checked sources (a whole forum in one)</span>
        {#if sourceOpts.length === 0}<span class="pnone">no sources yet</span>{/if}
        {#each sourceOpts as s (s.id)}
          <label class="popt">
            <input type="checkbox" checked={selectedSources.has(s.id)} onchange={() => toggleSource(s.id)} />
            <span class="ptitle">{s.title}</span>
            <span class="pcount">{s.count}</span>
          </label>
        {/each}
      </div>
    </details>

    <details class="pop">
      <summary>{selectedCountries.size ? `${selectedCountries.size} countr${selectedCountries.size > 1 ? 'ies' : 'y'}` : 'Countries'}</summary>
      <div class="pmenu">
        <span class="phint">victim country (geo verdict, not body text)</span>
        {#if countryOpts.length === 0}<span class="pnone">no country verdicts yet</span>{/if}
        {#each countryOpts as c (c.code)}
          <label class="popt">
            <input type="checkbox" checked={selectedCountries.has(c.code)} onchange={() => toggleCountry(c.code)} />
            <span class="ptitle">{c.code}</span>
            <span class="pcount">{c.count}</span>
          </label>
        {/each}
      </div>
    </details>
  {/snippet}

  {#snippet head()}
    <div class="lrow">
      <span class="lk">model</span>
      <div class="badges">
        {#each sel.labels as l}<Badge tone={incidentTone(l)}>{incidentLabelName(l)}</Badge>{/each}
        {#if !sel.labels.length}<span class="none">none</span>{/if}
      </div>
    </div>
    {#if sel.correctedLabels}
      <div class="lrow">
        <span class="lk truth">operator</span>
        <div class="badges">
          {#each sel.correctedLabels as l}<Badge tone={incidentTone(l)} dot>{incidentLabelName(l)}</Badge>{/each}
          {#if !sel.correctedLabels.length}<span class="none fp">false positive</span>{/if}
          <span class="by">by {sel.correctedBy} · {sel.correctedAt}</span>
        </div>
      </div>
    {/if}
    <div class="ctx">
      {#if sel.group}<span class="cwhere">in {sel.group}</span>{/if}
      {#if sel.victimCountry}<span class="cwhere">victim {sel.victimCountry}</span>{/if}
      {#if sel.actorHandle || sel.actorId}
        <span class="cwho">from
          {#if sel.actorId}<a class="alink" href={`/actors?id=${sel.actorId}`}>{sel.actorHandle || sel.actorId.slice(0, 8)}</a>{:else}{sel.actorHandle}{/if}
        </span>
      {/if}
    </div>
    <p class="meta">model {sel.modelVersion} · classified {sel.classifiedAt}</p>

    <div class="relabel">
      {#if editing}
        <div class="chips">
          {#each INCIDENT_LABELS as l}
            <button type="button" class="chip" class:on={draft.has(l)} onclick={() => toggle(l)}>{incidentLabelName(l)}</button>
          {/each}
        </div>
        <div class="reasons">
          {#each REASON_PRESETS as r}
            <button type="button" class="chip" class:on={!customReason && reason === r}
              onclick={() => { reason = r; customReason = false; }}>{r}</button>
          {/each}
          <button type="button" class="chip" class:on={customReason}
            onclick={() => { customReason = true; reason = ''; }}>Custom…</button>
        </div>
        {#if customReason}
          <input class="fin" type="text" bind:value={reason} placeholder="Custom reason (recorded to the audit chain)" />
        {/if}
        <div class="ra">
          <Button variant="primary" size="sm" disabled={!canSave} onclick={save}>Save correction</Button>
          <Button variant="ghost" size="sm" onclick={() => (editing = false)}>Cancel</Button>
          <span class="hint">reason required · empty labels = false positive</span>
        </div>
      {:else}
        <button class="editlink" onclick={() => (editing = true)}>{sel.correctedLabels ? 'edit correction' : 'correct labels'}</button>
      {/if}
      {#if incidentEdit.msg}<span class="submitmsg" class:err={incidentEdit.msg.startsWith('Failed')}>{incidentEdit.msg}</span>{/if}
    </div>
  {/snippet}

  {#snippet body()}
    <div class="tiles">
      <StatTile label="Fired labels" value={sel.labels.length} />
      <StatTile label="Model" value={sel.modelVersion} />
      <StatTile label="Classified" value={sel.classifiedAt.split(' ')[0]} sub={sel.classifiedAt.split(' ')[1] ?? ''} />
    </div>

    <Panel title="Message">
      {#if sel.body}
        <pre class="msg">{sel.body}</pre>
      {:else}
        <div class="empty">Message body unavailable (row removed or not retained).</div>
      {/if}
    </Panel>

    <Panel title="Per-head scores">
      {#snippet action()}<span class="count">{sel.scoreRows.length} heads</span>{/snippet}
      {#if sel.scoreRows.length}
        {#each sel.scoreRows as [label, prob]}
          {@const fired = sel.labels.includes(label)}
          <div class="srow" class:fired>
            <span class="slabel">{incidentLabelName(label)}</span>
            <span class="sbar"><span class="sfill" class:fired style="width:{Math.round(prob * 100)}%"></span></span>
            <span class="sval">{prob.toFixed(3)}</span>
            {#if fired}<Badge tone={incidentTone(label)} dot>fired</Badge>{/if}
          </div>
        {/each}
      {:else}
        <div class="empty">No per-head scores recorded.</div>
      {/if}
    </Panel>

    <Panel title="Evidence">
      <div class="ev"><span class="k">Message ID</span><span class="v mono">{sel.id}</span></div>
    </Panel>
  {/snippet}

  {#snippet empty()}
    <p class="pnote">
      {#if !incidentCtx.loaded}Loading…{:else if incidentCtx.error}Could not load incidents: {incidentCtx.error}{:else}No incidents detected yet. Run the classifier or `eyenet incidents-backfill`.{/if}
    </p>
  {/snippet}
</DossierLayout>

<style>
  .mid { font-family: var(--font-mono); font-size: var(--fs-22); font-weight: var(--fw-bold); letter-spacing: var(--tracking-data); color: var(--text); }
  .mid.muted { color: var(--text-faint); }
  .fcount { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); white-space: nowrap; margin-right: 2px; }
  .oftotal { color: var(--text-muted); }
  .search { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; min-width: 200px; }
  .search:focus { outline: none; border-color: var(--accent); }

  /* native <details> checkbox popover: zero-JS open/close, multi-select stays open */
  .pop { position: relative; }
  .pop > summary { list-style: none; cursor: pointer; user-select: none; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); padding: 6px 12px; white-space: nowrap; }
  .pop > summary::-webkit-details-marker { display: none; }
  .pop[open] > summary { border-color: var(--accent); }
  .pmenu { position: absolute; z-index: 40; top: calc(100% + 4px); right: 0; min-width: 200px; max-height: 320px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; padding: 8px; background: var(--panel); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: var(--shadow-2, 0 8px 24px rgba(0,0,0,0.4)); }
  .popt { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: var(--radius); font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); cursor: pointer; white-space: nowrap; }
  .popt:hover { background: var(--panel-2); }
  .popt input { accent-color: var(--accent); }
  .ptitle { flex: 1; overflow: hidden; text-overflow: ellipsis; }
  .pcount { color: var(--text-faint); font-size: var(--fs-11); }
  .phint { padding: 2px 6px 6px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .pgroup { padding: 8px 6px 2px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .pgroup:first-child { padding-top: 2px; }
  .pnone { padding: 4px 6px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .lrow { display: flex; align-items: baseline; gap: 10px; margin: 10px 0 0; }
  .lk { font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); min-width: 62px; }
  .lk.truth { color: var(--accent-text); }
  .none { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .none.fp { color: var(--warn-text); }
  .by { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .meta { margin: 8px 0 0; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .ctx { margin: 8px 0 0; display: flex; gap: 12px; flex-wrap: wrap; font-family: var(--font-mono); font-size: var(--fs-12); }
  .cwhere { color: var(--text-body); }
  .cwho { color: var(--text-muted); }
  .alink { color: var(--accent-text); text-decoration: none; }
  .alink:hover { text-decoration: underline; }

  .relabel { margin: 10px 0 0; display: flex; flex-direction: column; gap: 8px; }
  .chips, .reasons { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { appearance: none; padding: 3px 9px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); cursor: pointer; }
  .chip:hover { background: var(--panel-2); }
  .chip.on { background: var(--accent-fill); border-color: var(--accent); color: var(--text); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; max-width: 60ch; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .ra { display: flex; align-items: center; gap: 8px; }
  .hint { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .editlink { align-self: flex-start; appearance: none; background: none; border: none; cursor: pointer; padding: 0; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--accent-text); text-decoration: underline; }
  .submitmsg { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--accent-text); }
  .submitmsg.err { color: var(--red-text); }

  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote { margin: 0; padding: 16px 20px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .srow { display: grid; grid-template-columns: 130px 1fr 64px auto; gap: 10px; align-items: center; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .srow:last-child { border-bottom: none; }
  .slabel { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-muted); }
  .srow.fired .slabel { color: var(--text-body); }
  .sbar { height: 6px; border-radius: 3px; background: var(--panel-2); overflow: hidden; }
  .sfill { display: block; height: 100%; background: var(--border-strong); }
  .sfill.fired { background: var(--accent); }
  .sval { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); text-align: right; }

  .ev { display: grid; grid-template-columns: 110px 1fr; gap: 10px; align-items: baseline; padding: 6px 12px; }
  .ev .k { font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .ev .v { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); }
  .ev .v.mono { font-family: var(--font-mono); font-size: var(--fs-12); }

  .msg { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-13); line-height: var(--lh-normal); color: var(--text-body); white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow-y: auto; }
</style>
