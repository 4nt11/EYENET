<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import EntityList from '$lib/components/EntityList.svelte';
  import BehavePanel from '$lib/components/BehavePanel.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import { actorCtx, actorView, loadActors, loadActorDetail, saveAssessment } from '$lib/actor.svelte.js';

  const OBS_COLUMNS = [
    { key: 'ts', header: 'Timestamp', mono: true, width: '150px' },
    { key: 'kind', header: 'Primitive', mono: true, width: '220px' },
    { key: 'value', header: 'Value', mono: true },
    { key: 'sensitivity', header: 'Tier', mono: true, width: '90px' }
  ];

  // Deep-link support: /actors?id=<uuid> (e.g. click-through from the graph).
  let selectedId = $state(null);
  $effect(() => {
    const q = $page.url.searchParams.get('id');
    if (q) selectedId = q;
  });
  let a = $derived(actorCtx.list.find((x) => x.id === selectedId) ?? actorCtx.list[0] ?? null);
  let d = $derived(actorView.detail);

  // Assessment editor (local draft + reason).
  let assessmentDraft = $state('');
  let assessmentReason = $state('');
  let editingAssessment = $state(false);
  $effect(() => {
    // Reset the draft whenever the loaded actor's assessment changes.
    assessmentDraft = actorView.assessment ?? '';
    editingAssessment = false;
    assessmentReason = '';
  });

  $effect(() => { if (a) loadActorDetail(a.id); });

  onMount(loadActors);

  const assessmentReady = $derived(
    assessmentDraft.trim().length > 0 && assessmentReason.trim().length > 0 && !actorView.submitting
  );

  async function onSaveAssessment() {
    const ok = await saveAssessment(a.id, assessmentDraft.trim(), assessmentReason.trim());
    if (ok) editingAssessment = false;
  }
</script>

<EntityList label="Actors" items={actorCtx.list.map((x) => ({ id: x.id, primary: x.handle, secondary: x.id }))}
  selectedId={a?.id} onSelect={(id) => (selectedId = id)} />

<main>
  {#if a && d}
    <div class="dossier-head">
      <div class="head-top">
        <div class="handle-wrap">
          <span class="handle">{d.handle}</span>
          <span class="aid">{d.actorId}</span>
        </div>
        <div class="head-actions">
          {#if d.personaId}<a class="pbtn" href="/personas">View persona</a>{/if}
        </div>
      </div>
      <div class="badges">
        {#if d.platforms.length}<Badge tone="neutral">{d.platforms.join(' · ')}</Badge>{/if}
        {#if d.personaId}<Badge tone="high" dot>persona {d.personaId.slice(0, 8)}</Badge>{/if}
      </div>

      <!-- Operator assessment (write:actors) -->
      <div class="assess">
        {#if editingAssessment}
          <textarea class="fin area" rows="2" bind:value={assessmentDraft} placeholder="Operator assessment…"></textarea>
          <input class="fin" type="text" bind:value={assessmentReason} placeholder="Reason (for the audit record)" />
          <div class="assess-actions">
            <Button variant="primary" size="sm" disabled={!assessmentReady} onclick={onSaveAssessment}>Save</Button>
            <Button variant="ghost" size="sm" onclick={() => (editingAssessment = false)}>Cancel</Button>
          </div>
        {:else}
          <p class="assessment">{actorView.assessment || 'No operator assessment.'}</p>
          <button class="editlink" onclick={() => (editingAssessment = true)}>edit</button>
        {/if}
        {#if actorView.submitMsg}<span class="submitmsg" class:err={actorView.submitMsg.startsWith('Failed')}>{actorView.submitMsg}</span>{/if}
      </div>
      {#if actorView.aliases.length}<p class="aliases">aliases: {actorView.aliases.join(', ')}</p>{/if}
    </div>

    <div class="body">
      <div class="tiles">
        <StatTile label="Observations" value={d.observationCount} />
        <StatTile label="Aliases" value={d.aliasCount} />
        <StatTile label="First seen" value={d.firstSeen.split(' ')[0]} sub={d.firstSeen.split(' ')[1] ?? ''} />
        <StatTile label="Last seen" value={d.lastSeen.split(' ')[0]} sub={d.lastSeen.split(' ')[1] ?? ''} />
      </div>

      {#if actorView.behave}<BehavePanel behave={actorView.behave} />{/if}

      <div class="cols">
        <Panel title="Observations" class="grow">
          {#snippet action()}<span class="count">{actorView.observations.length} of {d.observationCount}</span>{/snippet}
          {#if actorView.observations.length}
            <DataTable rowKey="observation_id" columns={OBS_COLUMNS} rows={actorView.observations} />
          {:else}
            <div class="empty">No observations.</div>
          {/if}
        </Panel>

        <div class="side">
          <Panel title="Neighbors">
            {#if actorView.neighbors.length}
              {#each actorView.neighbors as n}
                <div class="nrow">
                  {#if n.edge_type === 'belongs_to_persona'}
                    <span class="ntype accent">persona</span>
                    <span class="ntarget">{n.target_id}</span>
                    <span class="ndetail">since {n.since}</span>
                  {:else}
                    <span class="ntype">linked</span>
                    <span class="ntarget">{n.target_id}</span>
                    <span class="ndetail">{n.state} · {n.method} · {n.score?.toFixed(2)}</span>
                  {/if}
                </div>
              {/each}
            {:else}
              <div class="empty">No neighbors.</div>
            {/if}
          </Panel>

          <Panel title="Timeline">
            {#if actorView.timeline.length}
              {#each actorView.timeline as t}
                <div class="trow">
                  <span class="tts">{t.ts}</span>
                  <span class="tkind" class:obs={t.kind === 'observation'}>{t.kind}</span>
                  <span class="tsum">{t.summary}</span>
                </div>
              {/each}
            {:else}
              <div class="empty">No timeline entries.</div>
            {/if}
          </Panel>
        </div>
      </div>
    </div>
  {:else}
    <p class="pnote">
      {#if !actorCtx.loaded}Loading…{:else if actorCtx.error}Could not load actors: {actorCtx.error}{:else}No actors yet.{/if}
    </p>
  {/if}
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }

  .dossier-head { flex: 0 0 auto; padding: 16px 20px 16px 22px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--border-strong); }
  .head-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .handle-wrap { display: flex; align-items: baseline; gap: 10px; }
  .handle { font-family: var(--font-mono); font-size: var(--fs-22); font-weight: var(--fw-bold); letter-spacing: var(--tracking-data); color: var(--text); }
  .aid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .head-actions { display: flex; gap: 8px; flex: 0 0 auto; }
  .pbtn { display: inline-flex; align-items: center; height: 28px; padding: 0 12px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-12); text-decoration: none; }
  .pbtn:hover { background: var(--panel-2); }
  .badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0 0; }

  .assess { margin: 10px 0 0; display: flex; flex-direction: column; gap: 6px; }
  .assessment { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); max-width: 90ch; display: inline; }
  .editlink { align-self: flex-start; appearance: none; background: none; border: none; cursor: pointer; padding: 0; font-family: var(--font-sans); font-size: var(--fs-11); color: var(--accent-text); text-decoration: underline; }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; max-width: 90ch; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .area { resize: vertical; }
  .assess-actions { display: flex; gap: 8px; }
  .submitmsg { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--accent-text); }
  .submitmsg.err { color: var(--red-text); }
  .aliases { margin: 8px 0 0; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .cols { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr); gap: 16px; align-items: start; margin-top: 16px; }
  :global(.panel.grow) { min-height: 160px; }
  .side { display: flex; flex-direction: column; gap: 16px; }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote { margin: 0; padding: 16px 20px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .nrow { display: grid; grid-template-columns: 70px 90px 1fr; gap: 10px; align-items: baseline; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .nrow:last-child { border-bottom: none; }
  .ntype { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-muted); }
  .ntype.accent { color: var(--accent-text); }
  .ntarget { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); }
  .ndetail { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .trow { display: grid; grid-template-columns: 150px 84px 1fr; gap: 10px; align-items: baseline; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .trow:last-child { border-bottom: none; }
  .tts { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .tkind { font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-muted); }
  .tkind.obs { color: var(--accent-text); }
  .tsum { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); }

  @media (max-width: 980px) { .cols { grid-template-columns: 1fr; } }
</style>
