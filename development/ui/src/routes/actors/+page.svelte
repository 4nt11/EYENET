<script>
  import EntityList from '$lib/components/EntityList.svelte';
  import BehavePanel from '$lib/components/BehavePanel.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import { ACTORS, ACTOR_OBS_COLUMNS, THREAT_LABEL } from '$lib/data.js';

  let selectedId = $state(ACTORS[0].actor_id);
  let a = $derived(ACTORS.find((x) => x.actor_id === selectedId) ?? ACTORS[0]);

  let listItems = $derived(ACTORS.map((x) => ({ id: x.actor_id, primary: x.primary_handle, secondary: x.actor_id, tier: x.tier })));
  const railColor = (t) => (t === 'critical' ? 'var(--red)' : t === 'high' ? 'var(--accent)' : 'var(--border-strong)');
</script>

<EntityList label="Threat actors" items={listItems} {selectedId} onSelect={(id) => (selectedId = id)} />

<main>
  <!-- Danger header -->
  <div class="dossier-head" class:critical={a.tier === 'critical'} style="--rail:{railColor(a.tier)};">
    <div class="head-top">
      <div class="handle-wrap">
        <span class="handle">{a.primary_handle}</span>
        <span class="aid">{a.actor_id}</span>
      </div>
      <div class="head-actions">
        {#if a.persona_id}<Button variant="ghost" size="sm">View persona {a.persona_id}</Button>{/if}
        <Button variant="primary" size="sm">Propose linkage</Button>
      </div>
    </div>
    <div class="badges">
      <Badge tone={a.tier} dot>Threat {THREAT_LABEL[a.tier]}</Badge>
      <Badge tone="neutral">{a.platforms.join(' · ')}</Badge>
      <Badge tone="neutral">recipe {a.recipe.name}</Badge>
      <Badge tone="high">role {a.role_signal}</Badge>
      {#if a.persona_id}<Badge tone="high" dot>persona {a.persona_id}</Badge>{/if}
    </div>
    {#if a.groups?.length}
      <div class="groups">
        <span class="glabel">in</span>
        {#each a.groups as g}
          <a class="gpill" href="/monitored-groups" title={`Go to ${g.name} (${g.platform})`}>
            <span class="gdot"></span>{g.name}<span class="garrow">→</span>
          </a>
        {/each}
      </div>
    {/if}
    <p class="assessment">{a.assessment}</p>
    <p class="aliases">aliases: {a.aliases.join(', ')}</p>
  </div>

  <div class="body">
    <div class="tiles">
      <StatTile label="Observations" value={a.observation_count} />
      <StatTile label="Aliases" value={a.alias_count} />
      <StatTile label="Score" value={a.score == null ? '·' : a.score.toFixed(2)} tone="accent" />
      <StatTile label="First seen" value={a.first_seen.split(' ')[0]} sub={a.first_seen.split(' ')[1]} />
      <StatTile label="Last seen" value={a.last_seen.split(' ')[0]} sub={a.last_seen.split(' ')[1]} />
    </div>

    <BehavePanel behave={a.behave} />

    <div class="cols">
      <Panel title="Observations" class="grow">
        {#snippet action()}<span class="count">{a.observations.length} of {a.observation_count}</span>{/snippet}
        <DataTable rowKey="observation_id" columns={ACTOR_OBS_COLUMNS} rows={a.observations} />
      </Panel>

      <div class="side">
        <Panel title="Neighbors">
          {#each a.neighbors as n}
            <div class="nrow">
              {#if n.edge_type === 'belongs_to_persona'}
                <span class="ntype accent">persona</span>
                <span class="ntarget">{n.target_id}</span>
                <span class="ndetail">since {n.since}</span>
              {:else}
                <span class="ntype">linked</span>
                <span class="ntarget">{n.target_id}</span>
                <span class="ndetail">{n.state} · {n.method} · {n.score.toFixed(2)}</span>
              {/if}
            </div>
          {/each}
        </Panel>

        <Panel title="Timeline">
          {#each a.timeline as t}
            <div class="trow">
              <span class="tts">{t.ts}</span>
              <span class="tkind" class:obs={t.kind === 'observation'}>{t.kind}</span>
              <span class="tsum">{t.summary}</span>
            </div>
          {/each}
        </Panel>
      </div>
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }

  .dossier-head { flex: 0 0 auto; padding: 16px 20px 16px 22px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--rail); }
  .dossier-head.critical { background: var(--red-fill); }
  .head-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .handle-wrap { display: flex; align-items: baseline; gap: 10px; }
  .handle { font-family: var(--font-mono); font-size: var(--fs-22); font-weight: var(--fw-bold); letter-spacing: var(--tracking-data); color: var(--text); }
  .aid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .head-actions { display: flex; gap: 8px; flex: 0 0 auto; }
  .badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0 0; }

  .groups { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 8px 0 0; }
  .glabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .gpill {
    display: inline-flex; align-items: center; gap: 6px;
    height: 20px; padding: 0 9px;
    border: 1px solid var(--accent); border-radius: 999px;
    background: var(--accent-fill);
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data);
    color: var(--accent-text); text-decoration: none;
    transition: background 120ms ease;
  }
  .gpill:hover { background: var(--accent-fill-strong); }
  .gdot { width: 5px; height: 5px; border-radius: 50%; background: var(--accent-text); flex: 0 0 auto; }
  .garrow { color: var(--accent-text); opacity: .8; }
  .assessment { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); max-width: 90ch; }
  .aliases { margin: 6px 0 0; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(172px, 1fr)); gap: 12px; margin-bottom: 16px; }

  .cols { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr); gap: 16px; align-items: start; margin-top: 16px; }
  :global(.panel.grow) { min-height: 160px; }
  .side { display: flex; flex-direction: column; gap: 16px; }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }

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
