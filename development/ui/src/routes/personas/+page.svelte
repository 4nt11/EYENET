<script>
  import EntityList from '$lib/components/EntityList.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import { PERSONAS, THREAT_LABEL } from '$lib/data.js';

  let selectedId = $state(PERSONAS[0].persona_id);
  let p = $derived(PERSONAS.find((x) => x.persona_id === selectedId) ?? PERSONAS[0]);

  let listItems = $derived(PERSONAS.map((x) => ({ id: x.persona_id, primary: x.label, secondary: `${x.member_count} member${x.member_count === 1 ? '' : 's'}`, tier: x.tier })));
  const railColor = (t) => (t === 'critical' ? 'var(--red)' : t === 'high' ? 'var(--accent)' : 'var(--border-strong)');
</script>

<EntityList label="Personas" items={listItems} {selectedId} onSelect={(id) => (selectedId = id)} />

<main>
  <div class="dossier-head" class:critical={p.tier === 'critical'} style="--rail:{railColor(p.tier)};">
    <div class="head-top">
      <div class="label-wrap">
        <span class="label">{p.label}</span>
        <span class="pid">{p.persona_id}</span>
      </div>
      <div class="head-actions">
        <Button variant="primary" size="sm">Merge</Button>
        <Button variant="ghost" size="sm">Split</Button>
      </div>
    </div>
    <div class="badges">
      <Badge tone={p.tier} dot>Threat {THREAT_LABEL[p.tier]}</Badge>
      <Badge tone="neutral">{p.member_count} attributed</Badge>
    </div>
    <p class="summary">{p.summary}</p>
  </div>

  <div class="body">
    <div class="tiles">
      <StatTile label="Members" value={p.member_count} tone="accent" />
      <StatTile label="Confirmed linkages" value={p.linkages.length} />
      <StatTile label="Created" value={p.created_at.split(' ')[0]} sub={p.created_at.split(' ')[1]} />
      <StatTile label="Updated" value={p.updated_at.split(' ')[0]} sub={p.updated_at.split(' ')[1]} />
    </div>

    <div class="cols">
      <Panel title="Attributed actors">
        {#each p.members as m}
          <div class="mrow">
            <span class="mhandle">{m.primary_handle}</span>
            <span class="mid">{m.actor_id}</span>
            <Badge tone={m.tier} dot>{m.tier}</Badge>
            <span class="msince">since {m.since}</span>
            <span class="mvia">{m.via_linkage_id ?? 'seed'}</span>
          </div>
        {/each}
      </Panel>

      <Panel title="Attribution basis">
        {#if p.linkages.length}
          {#each p.linkages as l}
            <div class="lblock">
              <div class="lhead">
                <span class="lid">{l.linkage_id}</span>
                <span class="lpair">{l.actor_a_id} ↔ {l.actor_b_id}</span>
                <Badge tone={l.state === 'confirmed' ? 'neutral' : 'high'} dot>{l.state}</Badge>
                <span class="lscore">{l.method} · {l.score.toFixed(2)}</span>
              </div>
              {#each l.evidence as e}
                <div class="erow">
                  <span class="ecmp">{e.comparator}</span>
                  <span class="escore">{e.score.toFixed(2)}</span>
                  <span class="edetail">{e.detail}</span>
                </div>
              {/each}
            </div>
          {/each}
        {:else}
          <div class="empty">Single-actor persona · no cross-actor linkages.</div>
        {/if}
      </Panel>
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }

  .dossier-head { flex: 0 0 auto; padding: 16px 20px 16px 22px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--rail); }
  .dossier-head.critical { background: var(--red-fill); }
  .head-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .label-wrap { display: flex; align-items: baseline; gap: 10px; }
  .label { font-family: var(--font-mono); font-size: var(--fs-22); font-weight: var(--fw-bold); letter-spacing: var(--tracking-data); color: var(--text); }
  .pid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .head-actions { display: flex; gap: 8px; flex: 0 0 auto; }
  .badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
  .summary { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); max-width: 90ch; }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }

  .mrow { display: grid; grid-template-columns: 130px 96px 80px 1fr 90px; gap: 10px; align-items: center; padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .mrow:last-child { border-bottom: none; }
  .mhandle { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); }
  .mid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .msince { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .mvia { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-align: right; }

  .lblock { padding: 10px 12px; border-bottom: 1px solid var(--border); }
  .lblock:last-child { border-bottom: none; }
  .lhead { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
  .lid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); }
  .lpair { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .lscore { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); margin-left: auto; }
  .erow { display: grid; grid-template-columns: minmax(0, 1.6fr) 60px 1fr; gap: 10px; align-items: baseline; padding: 2px 0 2px 10px; }
  .ecmp { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); }
  .escore { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); }
  .edetail { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }

  @media (max-width: 980px) { .cols { grid-template-columns: 1fr; } }
</style>
