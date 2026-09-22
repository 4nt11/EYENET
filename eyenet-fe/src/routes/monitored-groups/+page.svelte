<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import PlannedBanner from '$lib/components/PlannedBanner.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import { MONITORED_GROUPS, MGROUP_COLUMNS } from '$lib/data.js';

  let selectedId = $state(MONITORED_GROUPS[0].id);
  let g = $derived(MONITORED_GROUPS.find((x) => x.id === selectedId) ?? MONITORED_GROUPS[0]);

  let detail = $derived([
    { label: 'Group', value: g.id },
    { label: 'Name', value: g.name },
    { label: 'Platform', value: g.platform },
    { label: 'Source', value: g.source_id ?? 'unlinked' },
    { label: 'Collector', value: g.collector ?? 'none' },
    { label: 'Messages', value: g.messages.toLocaleString() },
    { label: 'Last activity', value: g.last_activity }
  ]);
</script>

<main>
  <SectionHeader group="Discovery" slug="monitored-groups" title="Monitored groups" />
  <PlannedBanner>Backed by <code class="c">GroupTable</code> in the model layer, but no <code class="c">/v1/groups</code> route exists yet. This is a mock for design review.</PlannedBanner>

  <div class="body">
    <div class="table-col">
      <DataTable rowKey="id" columns={MGROUP_COLUMNS} rows={MONITORED_GROUPS}
        selectedId={selectedId} onRowClick={(r) => (selectedId = r.id)} />
    </div>

    <div class="detail-col">
      <EvidencePanel title={`Group · ${g.id}`} items={detail} labelWidth={110} />
      {#if g.seed_root}<div class="seed"><Badge tone="high" dot>seed root</Badge> promoted as a discovery seed</div>{/if}

      <Panel title={`Actors seen · ${g.actors_seen.length}`}>
        {#each g.actors_seen as h}
          <a class="arow" href="/actors">
            <span class="ahandle">{h}</span>
            <span class="agoto">open →</span>
          </a>
        {/each}
      </Panel>
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .c { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  .seed { display: flex; align-items: center; gap: 8px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }

  .arow { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 12px; border-bottom: 1px solid var(--border); text-decoration: none; }
  .arow:last-child { border-bottom: none; }
  .arow:hover { background: var(--panel-2); }
  .ahandle { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .agoto { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
