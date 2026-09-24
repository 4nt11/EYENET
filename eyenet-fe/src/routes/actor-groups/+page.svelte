<script>
  import { onMount } from 'svelte';
  import EntityList from '$lib/components/EntityList.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import { actorGroupCtx, crewCase, crewSweep, linkerRun, loadActorGroups, openCase, sweepCases, runInfra, detectCopypasta, prettyInfra } from '$lib/actorGroup.svelte.js';
  import { manualCrewCtx, manualCrewView, crewSearch, loadManualCrews, loadManualCrewDetail, createCrewWith, addMemberById, removeMember, deleteCrew, searchCrewActors, clearCrewSearch } from '$lib/manualCrew.svelte.js';

  async function runSweep() { const n = await sweepCases(); if (n !== null) await loadActorGroups(); }
  async function rebuildCrews() { const r = await runInfra(); if (r !== null) await loadActorGroups(); }

  // One merged list: manual crews (curated) first, then derived. The manual/derived
  // label rides the EntityList chip slot (like actor tiers).
  let selectedId = $state(null);
  let listItems = $derived([
    ...manualCrewCtx.list.map((m) => ({ id: m.id, primary: m.name, secondary: `${m.memberCount} members`, chip: 'manual', tone: 'high' })),
    ...actorGroupCtx.list.map((d) => ({ id: d.id, primary: d.name, secondary: `${d.size} accounts`, chip: 'derived', tone: 'neutral' }))
  ]);
  let selKind = $derived(
    manualCrewCtx.list.some((m) => m.id === selectedId) ? 'manual'
      : actorGroupCtx.list.some((d) => d.id === selectedId) ? 'derived' : null
  );
  let dc = $derived(actorGroupCtx.list.find((x) => x.id === selectedId) ?? null);
  let caseId = $derived(dc ? crewCase.byId[dc.id] : null);

  $effect(() => {
    if (listItems.length && !listItems.some((i) => i.id === selectedId)) selectedId = listItems[0].id;
  });
  $effect(() => { if (selKind === 'manual') loadManualCrewDetail(selectedId); });

  // Crew builder (create) + add-member share the live actor search.
  let creating = $state(false);
  let newName = $state('');
  let picked = $state([]);
  let cq = $state('');
  let addQ = $state('');
  let timer;
  function onSearch(v) { clearTimeout(timer); timer = setTimeout(() => searchCrewActors(v), 200); }
  function startCreate() { creating = true; newName = ''; picked = []; cq = ''; clearCrewSearch(); }
  function cancelCreate() { creating = false; clearCrewSearch(); }
  function togglePick(a) {
    picked = picked.some((p) => p.id === a.id) ? picked.filter((p) => p.id !== a.id) : [...picked, a];
  }
  async function submitCreate() {
    if (!newName.trim()) return;
    const id = await createCrewWith(newName.trim(), picked.map((p) => p.id));
    creating = false; clearCrewSearch(); selectedId = id;
  }
  async function addFromSearch(a) {
    if (selKind === 'manual') { await addMemberById(selectedId, a.id); addQ = ''; clearCrewSearch(); }
  }
  async function onDelete() { if (selKind === 'manual') { await deleteCrew(selectedId); selectedId = null; } }

  onMount(() => { loadActorGroups(); loadManualCrews(); });
</script>

{#snippet searchBox(query, setQuery, onPick, pickedIds)}
  <input class="search" type="search" placeholder="Search actors · @handle, alias, identifier…" value={query} oninput={(e) => { setQuery(e.target.value); onSearch(e.target.value); }} spellcheck="false" />
  {#if !crewSearch.idle}
    <div class="results">
      {#if crewSearch.loading}<div class="rempty">Searching…</div>
      {:else if !crewSearch.results.length}<div class="rempty">No actors match “{query}”.</div>
      {:else}
        {#each crewSearch.results as a}
          <button class="res" class:on={pickedIds?.includes(a.id)} onclick={() => onPick(a)}>
            <span class="reshandle">{a.handle}</span>
            <span class="resid">{a.id.slice(0, 8)}{#if pickedIds?.includes(a.id)} · added{/if}</span>
          </button>
        {/each}
      {/if}
    </div>
  {/if}
{/snippet}

<EntityList label="Crews" items={listItems} selectedId={selectedId} onSelect={(id) => { selectedId = id; creating = false; }} />

<main>
  {#if creating}
    <div class="dossier-head accent">
      <div class="head-top">
        <span class="handle">New crew</span>
        <div class="head-actions">
          <Button variant="primary" size="sm" disabled={!newName.trim()} onclick={submitCreate}>Create{picked.length ? ` · ${picked.length}` : ''}</Button>
          <button class="pbtn" onclick={cancelCreate}>Cancel</button>
        </div>
      </div>
      <div class="badges"><Badge tone="high" dot>manual</Badge></div>
    </div>
    <div class="body">
      <Panel title="Name"><div class="pad"><input class="search" type="text" placeholder="Crew name…" bind:value={newName} /></div></Panel>
      <Panel title={`Members${picked.length ? ` · ${picked.length}` : ''}`}>
        <div class="pad">
          {@render searchBox(cq, (v) => (cq = v), togglePick, picked.map((p) => p.id))}
          {#if picked.length}<div class="chips">{#each picked as p}<button class="chip pick" onclick={() => togglePick(p)}>{p.handle} ✕</button>{/each}</div>{/if}
        </div>
      </Panel>
    </div>

  {:else if selKind === 'derived' && dc}
    <div class="dossier-head">
      <div class="head-top">
        <span class="handle">{dc.name}</span>
        <div class="head-actions">
          <button class="pbtn" onclick={startCreate}>+ New crew</button>
          {#if caseId}<a class="pbtn accent" href={`/cases/${caseId}`}>Open case →</a>
          {:else}<Button variant="primary" size="sm" disabled={crewCase.submitting} onclick={() => openCase(dc)}>Open case</Button>{/if}
        </div>
      </div>
      <div class="badges"><Badge tone="neutral" dot>derived</Badge></div>
      <div class="ops">
        <button class="oplink" disabled={linkerRun.submitting} onclick={rebuildCrews}>{linkerRun.submitting ? 'rebuilding…' : 'rebuild crews'}</button>
        <button class="oplink" disabled={linkerRun.submitting} onclick={detectCopypasta}>detect copypasta</button>
        <button class="oplink" disabled={crewSweep.submitting} onclick={runSweep}>auto-open big-crew cases</button>
        {#if linkerRun.msg}<span class="opnote">{linkerRun.msg}</span>{/if}
        {#if crewSweep.opened !== null}<span class="opnote">opened {crewSweep.opened} case{crewSweep.opened === 1 ? '' : 's'}</span>{/if}
      </div>
      {#if crewCase.error}<div class="err">Could not open case: {crewCase.error}</div>{/if}
    </div>
    <div class="body">
      <div class="tiles">
        <StatTile label="Accounts" value={dc.size} />
        <StatTile label="Links" value={dc.edgeCount} />
        <StatTile label="Max score" value={dc.maxScore} tone="accent" />
      </div>
      <Panel title={`Shared infrastructure · ${dc.topInfra.length}`}>
        {#if dc.topInfra.length}<div class="chips">{#each dc.topInfra as tok}<span class="chip">{prettyInfra(tok)}</span>{/each}</div>
        {:else}<div class="rempty">No shared indicators recorded.</div>{/if}
      </Panel>
      <Panel title={`Links · ${dc.edgeCount}`}>
        {#if dc.links.length}
          {#each dc.links as l}<div class="lrow"><span class="lpair">{l.a} <span class="larrow">↔</span> {l.b}</span><span class="lshared">{l.shared.join(', ')}</span><span class="lscore">{l.score.toFixed(2)}</span></div>{/each}
        {:else}<div class="rempty">No links recorded.</div>{/if}
      </Panel>
      <Panel title={`Members · ${dc.members.length}`}>
        {#each dc.members as m}<div class="mrow"><span class="mlabel">{m.label}</span><span class="mid">{m.actor_id.slice(0, 8)}</span></div>{/each}
      </Panel>
    </div>

  {:else if selKind === 'manual' && manualCrewView.detail}
    {@const d = manualCrewView.detail}
    <div class="dossier-head accent">
      <div class="head-top">
        <span class="handle">{d.name}</span>
        <div class="head-actions">
          <button class="pbtn" onclick={startCreate}>+ New crew</button>
          <button class="pbtn danger" onclick={onDelete}>Delete crew</button>
        </div>
      </div>
      <div class="badges"><Badge tone="high" dot>manual</Badge>{#if d.createdAt}<span class="sub">created {d.createdAt}</span>{/if}</div>
    </div>
    <div class="body">
      <div class="tiles"><StatTile label="Members" value={d.members.length} tone="accent" /></div>
      <Panel title="Add member">
        <div class="pad">
          {@render searchBox(addQ, (v) => (addQ = v), addFromSearch, d.members.map((m) => m.actor_id))}
          {#if manualCrewView.msg}<div class="err">{manualCrewView.msg}</div>{/if}
        </div>
      </Panel>
      <Panel title={`Members · ${d.members.length}`}>
        {#each d.members as m}
          <div class="mrow"><span class="mlabel">{m.handle}{#if m.displayName} · {m.displayName}{/if}</span><button class="rm" disabled={manualCrewView.busy} onclick={() => removeMember(selectedId, m.actor_id)}>remove</button></div>
        {:else}<div class="rempty">No members yet. Search above to add.</div>{/each}
      </Panel>
    </div>

  {:else}
    <div class="dossier-head">
      <div class="head-top">
        <span class="handle">Actor groups</span>
        <div class="head-actions"><Button variant="primary" size="sm" onclick={startCreate}>+ New crew</Button></div>
      </div>
    </div>
    <div class="body"><p class="pnote">
      {#if !actorGroupCtx.loaded || !manualCrewCtx.loaded}Loading…
      {:else}No crews yet. Rebuild the shared-infrastructure linker, or create one above.{/if}
    </p></div>
  {/if}
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }

  .dossier-head { flex: 0 0 auto; padding: 16px 20px 16px 22px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--border-strong); }
  .dossier-head.accent { border-left-color: var(--accent); }
  .head-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .handle { font-family: var(--font-mono); font-size: var(--fs-22); font-weight: var(--fw-bold); letter-spacing: var(--tracking-data); color: var(--text); overflow: hidden; text-overflow: ellipsis; }
  .head-actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
  .badges { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 10px 0 0; }
  .sub { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .ops { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 10px 0 0; }
  .oplink { appearance: none; background: none; border: none; padding: 0; cursor: pointer; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--accent-text); text-decoration: underline; letter-spacing: var(--tracking-label); }
  .oplink:disabled { color: var(--text-faint); cursor: default; text-decoration: none; }
  .opnote { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }

  .pbtn { display: inline-flex; align-items: center; height: 28px; padding: 0 12px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-12); text-decoration: none; cursor: pointer; }
  .pbtn:hover { background: var(--panel-2); }
  .pbtn.accent { color: var(--accent-text); }
  .pbtn.danger { color: var(--red-text); border-color: var(--red-border, var(--border-strong)); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 16px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap: 12px; }

  .pad { padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px; }
  .chip { font-family: var(--font-mono); font-size: var(--fs-12); padding: 3px 8px; border: 1px solid var(--border); border-radius: 4px; color: var(--text-body); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip.pick { cursor: pointer; background: var(--accent-fill); border-color: var(--accent); color: var(--text); }

  .lrow { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) 48px; gap: 10px; align-items: baseline; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .lrow:last-child { border-bottom: none; }
  .lpair { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .larrow { color: var(--accent-text); }
  .lshared { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lscore { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-align: right; }
  .mrow { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .mrow:last-child { border-bottom: none; }
  .mlabel { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); }
  .mid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }

  .rempty, .pnote { padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .err { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red-text); padding: 6px 0 0; }

  .search { width: 100%; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 8px 10px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .search::placeholder { color: var(--text-faint); }
  .results { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius); max-height: 260px; overflow: auto; }
  .res { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding: 7px 10px; border: none; border-bottom: 1px solid var(--border); background: transparent; cursor: pointer; text-align: left; }
  .res:last-child { border-bottom: none; }
  .res:hover { background: var(--panel); }
  .res.on { background: var(--accent-fill); }
  .reshandle { font-family: var(--font-mono); font-size: var(--fs-13); color: var(--text-body); }
  .resid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }

  .rm { appearance: none; background: none; border: none; cursor: pointer; padding: 0; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--red-text); }
  .rm:disabled { opacity: 0.5; cursor: default; }
</style>
