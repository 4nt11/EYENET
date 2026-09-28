<script>
  import { onMount } from 'svelte';
  import DossierLayout from '$lib/components/DossierLayout.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Dropdown from '$lib/components/Dropdown.svelte';
  import Button from '$lib/components/Button.svelte';
  import { incidentTone, INCIDENT_LABELS } from '$lib/data.js';
  import { incidentCtx, incidentEdit, loadIncidents, relabelIncident } from '$lib/incident.svelte.js';

  const LABEL_OPTS = [{ v: '', l: 'All labels' }, ...INCIDENT_LABELS.map((l) => ({ v: l, l }))];
  let labelFilter = $state('');
  let search = $state('');
  let searchTimer;

  let selectedId = $state(null);
  let sel = $derived(incidentCtx.list.find((x) => x.id === selectedId) ?? incidentCtx.list[0] ?? null);

  onMount(() => loadIncidents());

  function applyFilter() {
    selectedId = null;
    loadIncidents(labelFilter || null, search.trim());
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
  items={incidentCtx.list.map((x) => ({ id: x.id, primary: x.labels.join(' · ') || x.idShort, secondary: (x.group ? x.group + ' · ' : '') + ((x.body ?? '').slice(0, 56) || x.idShort) }))}
  selectedId={sel?.id} onSelect={(id) => (selectedId = id)}
  selected={!!sel}>

  {#snippet title()}
    {#if sel}
      <span class="mid">message {sel.idShort}</span>
    {:else}
      <span class="mid muted">Incidents</span>
    {/if}
  {/snippet}

  {#snippet filters()}
    <div class="fcount">{incidentCtx.list.length} detection{incidentCtx.list.length === 1 ? '' : 's'}</div>
    <input class="search" type="search" placeholder="Search message body…" bind:value={search} oninput={onSearch} aria-label="Search incident message bodies" />
    <Dropdown options={LABEL_OPTS} bind:value={labelFilter} onchange={applyFilter} minWidth="150px" />
  {/snippet}

  {#snippet head()}
    <div class="lrow">
      <span class="lk">model</span>
      <div class="badges">
        {#each sel.labels as l}<Badge tone={incidentTone(l)}>{l}</Badge>{/each}
        {#if !sel.labels.length}<span class="none">none</span>{/if}
      </div>
    </div>
    {#if sel.correctedLabels}
      <div class="lrow">
        <span class="lk truth">operator</span>
        <div class="badges">
          {#each sel.correctedLabels as l}<Badge tone={incidentTone(l)} dot>{l}</Badge>{/each}
          {#if !sel.correctedLabels.length}<span class="none fp">false positive</span>{/if}
          <span class="by">by {sel.correctedBy} · {sel.correctedAt}</span>
        </div>
      </div>
    {/if}
    <div class="ctx">
      {#if sel.group}<span class="cwhere">in {sel.group}</span>{/if}
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
            <button type="button" class="chip" class:on={draft.has(l)} onclick={() => toggle(l)}>{l}</button>
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
            <span class="slabel">{label}</span>
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
  .search { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; min-width: 200px; }
  .search:focus { outline: none; border-color: var(--accent); }
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
