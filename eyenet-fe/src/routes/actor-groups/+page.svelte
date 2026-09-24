<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import EntityList from '$lib/components/EntityList.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import { actorGroupCtx, crewCase, loadActorGroups, openCase, prettyInfra } from '$lib/actorGroup.svelte.js';

  let caseId = $derived(c ? crewCase.byId[c.id] : null);

  let selectedId = $state(null);
  let c = $derived(
    actorGroupCtx.list.find((x) => x.id === selectedId) ?? actorGroupCtx.list[0] ?? null
  );
  let listItems = $derived(
    actorGroupCtx.list.map((x) => ({ id: x.id, primary: x.name, secondary: `${x.size} accounts` }))
  );

  onMount(loadActorGroups);
</script>

<main class="wrap">
  <SectionHeader group="Attribution" slug="actor-groups" title="Actor groups" />

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
</main>

<style>
  .wrap { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .split { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(260px, 340px) minmax(0, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .detail { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .name { font-family: var(--font-mono); font-size: var(--fs-16); color: var(--text-strong); letter-spacing: var(--tracking-data); }
  .badges { display: flex; gap: 8px; flex-wrap: wrap; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px; }
  .chip { font-family: var(--font-mono); font-size: var(--fs-12); padding: 3px 8px; border: 1px solid var(--border); border-radius: 4px; color: var(--text-body); }
  .mrow { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .mrow:last-child { border-bottom: none; }
  .mlabel { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); }
  .mid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .empty, .pnote { padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .caselink { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent); text-decoration: none; align-self: center; }
  .caselink:hover { text-decoration: underline; }
  .err { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--red); padding: 4px 0; }
  @media (max-width: 900px) { .split { grid-template-columns: 1fr; overflow: auto; } }
</style>
