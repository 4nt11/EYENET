<script>
  import { onMount } from 'svelte';
  import EntityList from '$lib/components/EntityList.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import MergePersonaDialog from '$lib/components/MergePersonaDialog.svelte';
  import SplitPersonaDialog from '$lib/components/SplitPersonaDialog.svelte';
  import { personaCtx, personaView, loadPersonas, loadPersonaDetail, mergePersona, splitPersona } from '$lib/persona.svelte.js';

  let selectedId = $state(null);
  let p = $derived(personaCtx.list.find((x) => x.id === selectedId) ?? personaCtx.list[0] ?? null);

  let listItems = $derived(
    personaCtx.list.map((x) => ({
      id: x.id,
      primary: x.label,
      secondary: `${x.memberCount} member${x.memberCount === 1 ? '' : 's'}`
    }))
  );

  let mergeOpen = $state(false);
  let splitOpen = $state(false);

  $effect(() => { if (p) loadPersonaDetail(p.id); });

  onMount(loadPersonas);

  async function onMerge({ otherPersonaId, reason, caseRefs }) {
    return mergePersona(p.id, otherPersonaId, reason, caseRefs);
  }
  async function onSplit({ actorId, reason, caseRefs }) {
    return splitPersona(p.id, actorId, reason, caseRefs);
  }
</script>

<EntityList label="Personas" items={listItems} selectedId={p?.id} onSelect={(id) => (selectedId = id)} />

<main>
  {#if p}
    <div class="dossier-head">
      <div class="head-top">
        <div class="label-wrap">
          <span class="label">{p.label}</span>
          <span class="pid">{p.id}</span>
        </div>
        <div class="head-actions">
          <Button variant="primary" size="sm" disabled={personaView.submitting} onclick={() => (mergeOpen = true)}>Merge</Button>
          <Button variant="ghost" size="sm" disabled={personaView.submitting || !personaView.members.length} onclick={() => (splitOpen = true)}>Split</Button>
        </div>
      </div>
      <div class="badges">
        <Badge tone="neutral">{personaView.memberCount} attributed</Badge>
      </div>
      {#if personaView.submitMsg}<p class="submitmsg" class:err={personaView.submitMsg.startsWith('Failed')}>{personaView.submitMsg}</p>{/if}
    </div>

    <div class="body">
      <div class="tiles">
        <StatTile label="Members" value={personaView.memberCount} tone="accent" />
        <StatTile label="Created" value={personaView.createdAt?.split(' ')[0] ?? '·'} sub={personaView.createdAt?.split(' ')[1] ?? ''} />
        <StatTile label="Updated" value={personaView.updatedAt?.split(' ')[0] ?? '·'} sub={personaView.updatedAt?.split(' ')[1] ?? ''} />
      </div>

      <Panel title="Attributed actors">
        {#if personaView.members.length}
          {#each personaView.members as m}
            <a class="mrow" href={`/actors?id=${m.actorId}`} title="Open actor dossier">
              <span class="mhandle">{m.handle}</span>
              <span class="mid">{m.actorId}</span>
              <span class="msince">since {m.since}</span>
              <span class="mvia">{m.viaLinkageId}</span>
              <span class="marrow">→</span>
            </a>
          {/each}
        {:else}
          <div class="empty">
            {#if personaView.loading}Loading…{:else if personaView.error}Could not load members: {personaView.error}{:else}No attributed actors.{/if}
          </div>
        {/if}
      </Panel>
    </div>

    <MergePersonaDialog bind:open={mergeOpen} persona={p} onconfirm={onMerge} />
    <SplitPersonaDialog bind:open={splitOpen} persona={p} members={personaView.members} onconfirm={onSplit} />
  {:else}
    <p class="pnote">
      {#if !personaCtx.loaded}Loading…{:else if personaCtx.error}Could not load personas: {personaCtx.error}{:else}No personas yet.{/if}
    </p>
  {/if}
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }

  .dossier-head { flex: 0 0 auto; padding: 16px 20px 16px 22px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--border-strong); }
  .head-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .label-wrap { display: flex; align-items: baseline; gap: 10px; }
  .label { font-family: var(--font-mono); font-size: var(--fs-22); font-weight: var(--fw-bold); letter-spacing: var(--tracking-data); color: var(--text); }
  .pid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .head-actions { display: flex; gap: 8px; flex: 0 0 auto; }
  .badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0 0; }
  .submitmsg { margin: 10px 0 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }
  .submitmsg.err { color: var(--red-text); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap: 12px; margin-bottom: 16px; }

  .mrow { display: grid; grid-template-columns: 150px 1fr 130px 110px 16px; gap: 10px; align-items: center; padding: 7px 12px; border-bottom: 1px solid var(--border); text-decoration: none; transition: background 120ms ease; }
  .mrow:last-child { border-bottom: none; }
  .mrow:hover { background: var(--panel-2); }
  .mrow:hover .mhandle, .mrow:hover .marrow { color: var(--accent-text); }
  .marrow { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); text-align: right; }
  .mhandle { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); }
  .mid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .msince { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .mvia { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-align: right; }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote { margin: 0; padding: 16px 20px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
</style>
