<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import PlannedBanner from '$lib/components/PlannedBanner.svelte';
  import EntityList from '$lib/components/EntityList.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import { ACTOR_GROUPS, THREAT_LABEL } from '$lib/data.js';

  let selectedId = $state(ACTOR_GROUPS[0].id);
  let c = $derived(ACTOR_GROUPS.find((x) => x.id === selectedId) ?? ACTOR_GROUPS[0]);
  let listItems = $derived(ACTOR_GROUPS.map((x) => ({ id: x.id, primary: x.name, secondary: x.id, tier: x.tier })));
  const railColor = (t) => (t === 'critical' ? 'var(--red)' : t === 'high' ? 'var(--accent)' : 'var(--border-strong)');
</script>

<div class="wrap">
  <PlannedBanner>Threat-actor crews (e.g. The Gentlemen, LulzSec) have no model or API in the codebase. This is a pure design proposal for a future engine surface.</PlannedBanner>
  <div class="split">
    <EntityList label="Actor groups" items={listItems} {selectedId} onSelect={(id) => (selectedId = id)} />

    <main>
      <div class="dossier-head" class:critical={c.tier === 'critical'} style="--rail:{railColor(c.tier)};">
        <div class="head-top">
          <div class="name-wrap"><span class="name">{c.name}</span><span class="cid">{c.id}</span></div>
          <Button variant="ghost" size="sm">Export crew brief</Button>
        </div>
        <div class="badges">
          <Badge tone={c.tier} dot>Threat {THREAT_LABEL[c.tier]}</Badge>
          <Badge tone="neutral">{c.members.length} member{c.members.length === 1 ? '' : 's'}</Badge>
          <Badge tone="neutral">first seen {c.first_seen}</Badge>
        </div>
        <p class="aka">aka: {c.aka.join(', ')}</p>
        <p class="assessment">{c.assessment}</p>
      </div>

      <div class="body">
        <div class="cols">
          <Panel title="Member personas">
            {#each c.members as m}
              <a class="mrow" href="/personas">
                <span class="mlabel">{m.label}</span>
                <span class="mpid">{m.persona}</span>
                <span class="mrole">{m.role}</span>
                <span class="mgoto">open →</span>
              </a>
            {/each}
          </Panel>

          <div class="side">
            <Panel title="TTPs">
              <div class="chips">
                {#each c.ttps as t}<span class="chip">{t}</span>{/each}
              </div>
            </Panel>
            <Panel title="Cases">
              <div class="chips">
                {#each c.cases as k}<a class="chip link" href="/cases">{k}</a>{/each}
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </main>
  </div>
</div>

<style>
  .wrap { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .split { flex: 1; min-height: 0; display: flex; overflow: hidden; }
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }

  .dossier-head { flex: 0 0 auto; padding: 16px 20px 16px 22px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--rail); }
  .dossier-head.critical { background: var(--red-fill); }
  .head-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .name-wrap { display: flex; align-items: baseline; gap: 10px; }
  .name { font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); }
  .cid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0 8px; }
  .aka { margin: 0 0 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .assessment { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); max-width: 90ch; }

  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
  .cols { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(260px, 1fr); gap: 16px; align-items: start; }
  .side { display: flex; flex-direction: column; gap: 16px; }

  .mrow { display: grid; grid-template-columns: 110px 96px 1fr 60px; gap: 10px; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--border); text-decoration: none; }
  .mrow:last-child { border-bottom: none; }
  .mrow:hover { background: var(--panel-2); }
  .mlabel { font-family: var(--font-mono); font-size: var(--fs-13); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .mpid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .mrole { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-secondary); }
  .mgoto { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); text-align: right; }

  .chips { display: flex; flex-wrap: wrap; gap: 7px; padding: 12px; }
  .chip { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 3px 8px; text-decoration: none; }
  .chip.link { color: var(--accent-text); border-color: var(--accent); }
  .chip.link:hover { background: var(--accent-fill); }

  @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
</style>
