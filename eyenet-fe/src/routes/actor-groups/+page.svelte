<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import EntityList from '$lib/components/EntityList.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import { actorGroupCtx, crewCase, crewSweep, linkerRun, loadActorGroups, openCase, sweepCases, runInfra, detectCopypasta, prettyInfra } from '$lib/actorGroup.svelte.js';
  import { manualCrewCtx, manualCrewView, loadManualCrews, loadManualCrewDetail, createCrew, addMember, removeMember, deleteCrew } from '$lib/manualCrew.svelte.js';

  let tab = $state('derived'); // 'derived' | 'manual'

  async function runSweep() {
    const n = await sweepCases();
    if (n !== null) await loadActorGroups();
  }
  async function rebuildCrews() {
    const r = await runInfra();
    if (r !== null) await loadActorGroups();
  }

  let caseId = $derived(c ? crewCase.byId[c.id] : null);

  let selectedId = $state(null);
  let c = $derived(
    actorGroupCtx.list.find((x) => x.id === selectedId) ?? actorGroupCtx.list[0] ?? null
  );
  let listItems = $derived(
    actorGroupCtx.list.map((x) => ({ id: x.id, primary: x.name, secondary: `${x.size} accounts` }))
  );

  // Manual crews
  let mSelectedId = $state(null);
  let mc = $derived(
    manualCrewCtx.list.find((x) => x.id === mSelectedId) ?? manualCrewCtx.list[0] ?? null
  );
  let mListItems = $derived(
    manualCrewCtx.list.map((x) => ({ id: x.id, primary: x.name, secondary: `${x.memberCount} members` }))
  );
  $effect(() => { if (tab === 'manual' && mc) loadManualCrewDetail(mc.id); });

  let newName = $state('');
  let addHandle = $state('');

  async function onCreate() {
    if (!newName.trim()) return;
    const id = await createCrew(newName.trim(), '');
    newName = '';
    mSelectedId = id;
  }
  async function onAdd() {
    if (!addHandle.trim() || !mc) return;
    const ok = await addMember(mc.id, addHandle.trim());
    if (ok) addHandle = '';
  }
  async function onDelete() {
    if (mc) await deleteCrew(mc.id);
  }

  onMount(() => { loadActorGroups(); loadManualCrews(); });
</script>

<main class="wrap">
  <SectionHeader group="Attribution" slug="actor-groups" title="Actor groups" />

  <div class="tabbar">
    <button class="tabx" class:on={tab === 'derived'} onclick={() => (tab = 'derived')}>Derived</button>
    <button class="tabx" class:on={tab === 'manual'} onclick={() => (tab = 'manual')}>Manual</button>
  </div>

{#if tab === 'derived'}
  <div class="toolbar">
    <Button variant="primary" size="sm" disabled={linkerRun.submitting} onclick={rebuildCrews}>
      {linkerRun.submitting ? 'Running…' : 'Rebuild crews (infra linker)'}
    </Button>
    <Button variant="ghost" size="sm" disabled={linkerRun.submitting} onclick={detectCopypasta}>
      Detect copypasta
    </Button>
    <Button variant="ghost" size="sm" disabled={crewSweep.submitting} onclick={runSweep}>
      {crewSweep.submitting ? 'Opening…' : 'Auto-open big-crew cases'}
    </Button>
    {#if linkerRun.msg}<span class="note">{linkerRun.msg}</span>{/if}
    {#if crewSweep.opened !== null}<span class="note">Opened {crewSweep.opened} case{crewSweep.opened === 1 ? '' : 's'}.</span>{/if}
    {#if linkerRun.error}<span class="err">{linkerRun.error}</span>{/if}
    {#if crewSweep.error}<span class="err">{crewSweep.error}</span>{/if}
  </div>

  <div class="split">
    {#if actorGroupCtx.list.length}
      <EntityList
        label="Crews"
        items={listItems}
        selectedId={c?.id}
        onSelect={(id) => (selectedId = id)}
      />

      <section class="detail">
        <div class="head">
          <span class="name">{c.name}</span>
          <div class="badges">
            <Badge tone="accent">{c.size} accounts</Badge>
            <Badge tone="neutral">{c.edgeCount} link{c.edgeCount === 1 ? '' : 's'}</Badge>
            <Badge tone="high">score {c.maxScore}</Badge>
            {#if caseId}
              <a class="caselink" href={`/cases/${caseId}`}>Open case →</a>
            {:else}
              <Button variant="primary" size="sm" disabled={crewCase.submitting} onclick={() => openCase(c)}>Open case</Button>
            {/if}
          </div>
        </div>
        {#if crewCase.error}<div class="err">Could not open case: {crewCase.error}</div>{/if}

        <Panel title={`Shared infrastructure · ${c.topInfra.length}`}>
          {#if c.topInfra.length}
            <div class="chips">
              {#each c.topInfra as tok}<span class="chip">{prettyInfra(tok)}</span>{/each}
            </div>
          {:else}
            <div class="empty">No shared indicators recorded.</div>
          {/if}
        </Panel>

        <Panel title={`Links · ${c.edgeCount}`}>
          {#if c.links.length}
            {#each c.links as l}
              <div class="lrow">
                <span class="lpair">{l.a} <span class="larrow">↔</span> {l.b}</span>
                <span class="lshared">{l.shared.join(', ')}</span>
                <span class="lscore">{l.score.toFixed(2)}</span>
              </div>
            {/each}
          {:else}
            <div class="empty">No links recorded.</div>
          {/if}
        </Panel>

        <Panel title={`Members · ${c.members.length}`}>
          {#each c.members as m}
            <div class="mrow"><span class="mlabel">{m.label}</span><span class="mid">{m.actor_id.slice(0, 8)}</span></div>
          {/each}
        </Panel>
      </section>
    {:else}
      <p class="pnote">
        {#if !actorGroupCtx.loaded}Loading...{:else if actorGroupCtx.error}Could not load actor groups: {actorGroupCtx.error}{:else}No crews yet. Run the shared-infrastructure linker (`eyenet link-infra`) once collectors have ingested traffic.{/if}
      </p>
    {/if}
  </div>
{:else}
  <div class="toolbar">
    <input class="fin" type="text" placeholder="New crew name…" bind:value={newName}
      onkeydown={(e) => e.key === 'Enter' && onCreate()} />
    <Button variant="primary" size="sm" disabled={!newName.trim()} onclick={onCreate}>Create crew</Button>
    {#if manualCrewCtx.error}<span class="err">{manualCrewCtx.error}</span>{/if}
  </div>

  <div class="split">
    {#if manualCrewCtx.list.length}
      <EntityList label="Manual crews" items={mListItems} selectedId={mc?.id} onSelect={(id) => (mSelectedId = id)} />

      <section class="detail">
        {#if manualCrewView.detail}
          {@const d = manualCrewView.detail}
          <div class="head">
            <span class="name">{d.name}</span>
            <div class="badges">
              <Badge tone="accent">{d.members.length} members</Badge>
              <button class="danger" onclick={onDelete}>Delete crew</button>
            </div>
          </div>

          <Panel title="Add member">
            <div class="addrow">
              <input class="fin" type="text" placeholder="@handle" bind:value={addHandle}
                onkeydown={(e) => e.key === 'Enter' && onAdd()} />
              <Button variant="primary" size="sm" disabled={manualCrewView.busy || !addHandle.trim()} onclick={onAdd}>Add</Button>
              {#if manualCrewView.msg}<span class="err">{manualCrewView.msg}</span>{/if}
            </div>
          </Panel>

          <Panel title={`Members · ${d.members.length}`}>
            {#each d.members as m}
              <div class="mrow">
                <span class="mlabel">{m.handle}{#if m.displayName} · {m.displayName}{/if}</span>
                <button class="rm" disabled={manualCrewView.busy} onclick={() => removeMember(mc.id, m.actor_id)}>remove</button>
              </div>
            {:else}
              <div class="empty">No members yet. Add one by @handle above.</div>
            {/each}
          </Panel>
        {:else}
          <p class="pnote">{manualCrewView.loading ? 'Loading…' : 'Select a crew.'}</p>
        {/if}
      </section>
    {:else}
      <p class="pnote">{manualCrewCtx.loaded ? 'No manual crews yet. Name one above to start curating.' : 'Loading…'}</p>
    {/if}
  </div>
{/if}
</main>

<style>
  .wrap { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .split { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(260px, 340px) minmax(0, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .detail { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  /* Panels keep natural height; the column scrolls. Without this, flex-shrink
     crushes the short infra panel to a sliver and overflow:hidden clips the chips. */
  .detail > :global(.panel) { flex: 0 0 auto; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .name { font-family: var(--font-mono); font-size: var(--fs-16); color: var(--text-strong); letter-spacing: var(--tracking-data); }
  .badges { display: flex; gap: 8px; flex-wrap: wrap; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px; }
  .chip { font-family: var(--font-mono); font-size: var(--fs-12); padding: 3px 8px; border: 1px solid var(--border); border-radius: 4px; color: var(--text-body); }
  .lrow { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) 48px; gap: 10px; align-items: baseline; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .lrow:last-child { border-bottom: none; }
  .lpair { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .larrow { color: var(--accent-text); }
  .lshared { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lscore { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-align: right; }
  .mrow { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .mrow:last-child { border-bottom: none; }
  .mlabel { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); }
  .mid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .empty, .pnote { padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .caselink { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent); text-decoration: none; align-self: center; }
  .caselink:hover { text-decoration: underline; }
  .err { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red); padding: 4px 0; }
  .toolbar { display: flex; align-items: center; gap: 12px; padding: 8px 20px 0; }
  .tabbar { display: flex; gap: 4px; padding: 8px 20px 0; }
  .tabx { appearance: none; padding: 5px 14px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-12); cursor: pointer; }
  .tabx:hover { background: var(--panel); }
  .tabx.on { color: var(--text); border-color: var(--accent); background: var(--accent-fill); }
  .fin { flex: 0 1 260px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .addrow { display: flex; align-items: center; gap: 10px; padding: 12px; }
  .danger { appearance: none; padding: 3px 10px; border: 1px solid var(--red-border, var(--border-strong)); border-radius: var(--radius); background: transparent; color: var(--red-text); font-family: var(--font-sans); font-size: var(--fs-11); cursor: pointer; }
  .danger:hover { background: var(--red-fill, var(--panel-2)); }
  .rm { appearance: none; background: none; border: none; cursor: pointer; padding: 0; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--red-text); }
  .rm:disabled { opacity: 0.5; cursor: default; }
  .note { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  @media (max-width: 900px) { .split { grid-template-columns: 1fr; overflow: auto; } }
</style>
