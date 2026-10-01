<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import {
    groupCtx, groupView, groupStatusTone, isJoinable, loadGroups, joinGroup, leaveGroup, scanGroups, short
  } from '$lib/group.svelte.js';
  import { collectorCtx, loadCollectors } from '$lib/collector.svelte.js';
  import { sourceCtx, loadSources } from '$lib/source.svelte.js';
  import { PLATFORMS } from '$lib/discovery-shape.js';

  // Resolve a group's source_id -> platform label (the SOURCE's platform, used
  // for the join-collector lease — not the candidate's own platform).
  const platformOf = (sourceId) =>
    sourceCtx.list.find((s) => s.id === sourceId)?.platform ?? short(sourceId);

  const COLUMNS = [
    { key: 'platform', header: 'Platform', mono: true, width: '88px' },
    { key: 'foundVia', header: 'Found via', mono: true, width: '104px' },
    { key: 'kind', header: 'Kind', mono: true, width: '84px' },
    { key: 'title', header: 'Group', mono: true },
    { key: 'status', header: 'Status', badge: true, tone: groupStatusTone, width: '150px' },
    { key: 'lastSeen', header: 'Last seen', mono: true, align: 'right', width: '170px' }
  ];

  // Client-side membership + real-platform filters over the server-narrowed set.
  // realPlatform is derived from the candidate shape (a telegram @handle found on
  // a forum is a telegram lead), so it can't be a server param — filter here.
  let member = $state('all'); // 'all' | 'member' | 'discovered'
  let platformFilter = $state(''); // '' | forum | telegram | matrix
  let memberCount = $derived(groupCtx.list.filter((g) => g.memberDialog).length);
  // Platform column shows the candidate's REAL platform (its shape), not the
  // observing source's.
  const rows = $derived(
    groupCtx.list
      .filter((g) => member === 'all' || (member === 'member' ? g.memberDialog : !g.memberDialog))
      .filter((g) => !platformFilter || g.realPlatform === platformFilter)
      .map((g) => ({ ...g, platform: g.realPlatform }))
  );

  let selectedId = $state(null);
  let sel = $derived(rows.find((g) => g.id === selectedId) ?? rows[0] ?? null);

  // Collectors on the selected group's platform lease cleanly for its join.
  const collectors = $derived(
    sel ? collectorCtx.list.filter((c) => c.kind === platformOf(sel.sourceId)) : []
  );
  let collectorId = $state('');
  $effect(() => { if (collectorId && !collectors.some((c) => c.id === collectorId)) collectorId = ''; });

  let detail = $derived(
    sel
      ? [
          { label: 'Group', value: sel.title },
          { label: 'Platform', value: sel.realPlatform },
          { label: 'Found via', value: sel.foundVia },
          { label: 'Kind', value: sel.kind || '—' },
          { label: 'Platform id', value: sel.platformGroupId },
          { label: 'Status', value: sel.status, tone: sel.status === 'monitored' ? 'accent' : undefined },
          { label: 'Member (dialog)', value: sel.memberDialog ? 'yes' : 'no' },
          { label: 'Source', value: `${platformOf(sel.sourceId)} · ${short(sel.sourceId)}` },
          ...(sel.groupId ? [{ label: 'Group id', value: short(sel.groupId) }] : [])
        ]
      : []
  );

  // Server-side narrowing: substring search + source filter, debounced so each
  // keystroke doesn't hammer the API. The initial run (empty) loads all.
  let search = $state('');
  let sourceFilter = $state('');
  $effect(() => {
    const s = search, src = sourceFilter;
    const t = setTimeout(() => loadGroups(s, src), 250);
    return () => clearTimeout(t);
  });

  onMount(() => {
    loadCollectors();
    loadSources();
  });

  async function join() {
    if (!sel || !collectorId) return;
    await joinGroup(sel.id, collectorId);
  }

  async function leave() {
    if (!sel) return;
    if (!window.confirm(`Leave and stop monitoring "${sel.title}"?`)) return;
    await leaveGroup(sel.id);
  }
</script>

<main>
  <div class="head">
    <SectionHeader group="Discovery" slug="monitored-groups" title="Monitored groups" />
    <Button variant="ghost" size="sm" disabled={groupView.submitting} onclick={scanGroups}>Rescan visibility</Button>
  </div>

  <div class="body">
    <div class="table-col">
      <div class="filter-bar">
        <input class="search" type="search" placeholder="Search by name or platform id…"
          bind:value={search} aria-label="Search groups" />
        <select class="source-sel" bind:value={sourceFilter} aria-label="Filter by source">
          <option value="">All sources</option>
          {#each sourceCtx.list as s}<option value={s.id}>{s.name} · {s.platform}</option>{/each}
        </select>
        <select class="source-sel" bind:value={platformFilter} aria-label="Filter by platform">
          <option value="">All platforms</option>
          {#each PLATFORMS as p}<option value={p}>{p}</option>{/each}
        </select>
        <div class="segs">
          <button class="seg" class:on={member === 'all'} onclick={() => (member = 'all')}>All · {groupCtx.list.length}</button>
          <button class="seg" class:on={member === 'discovered'} onclick={() => (member = 'discovered')}>Discovered · {groupCtx.list.length - memberCount}</button>
          <button class="seg" class:on={member === 'member'} onclick={() => (member = 'member')}>Already a member · {memberCount}</button>
        </div>
      </div>
      <div class="table-scroll">
      {#if rows.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={rows}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !groupCtx.loaded}Loading…{:else if groupCtx.error}Could not load groups: {groupCtx.error}{:else if groupCtx.list.length}No groups in this view.{:else if search.trim() || sourceFilter}No groups match the current filters.{:else}No groups visible yet. Run a collector (it scans its identity's groups on start), or Rescan.{/if}
        </p>
      {/if}
      </div>
    </div>

    {#if sel}
      <div class="detail-col">
        <EvidencePanel title={`Group · ${sel.title}`} items={detail} labelWidth={120} />
        <div class="actions">
          <div class="actions-label">Join / monitor</div>
          {#if isJoinable(sel.status)}
            <select class="fin" bind:value={collectorId}>
              <option value="" disabled>Assign a collector…</option>
              {#each collectors as c}<option value={c.id}>{c.name} · {c.observed}</option>{/each}
            </select>
            {#if !collectors.length}<span class="hint">No collector on this platform — create one first.</span>{/if}
            <Button variant="primary" size="sm" disabled={groupView.submitting || !collectorId} onclick={join}>Join group</Button>
          {:else if sel.status === 'monitored'}
            <Button variant="destructive" size="sm" disabled={groupView.submitting} onclick={leave}>Leave group</Button>
          {:else}
            <span class="hint">This group is {sel.status}; no action.</span>
          {/if}
          {#if groupView.submitMsg}<p class="hint">{groupView.submitMsg}</p>{/if}
        </div>
      </div>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-right: 20px; }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; display: flex; flex-direction: column; gap: 10px; }
  .table-scroll { flex: 1; min-height: 0; overflow: auto; }
  .filter-bar { display: flex; gap: 8px; flex-shrink: 0; flex-wrap: wrap; align-items: center; }
  .segs { display: flex; gap: 6px; }
  .search { flex: 1 1 220px; min-width: 160px; box-sizing: border-box; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .search::placeholder { color: var(--text-faint); }
  .source-sel { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; max-width: 220px; }
  .source-sel:focus { outline: none; border-color: var(--accent); }
  .seg { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 5px 10px; cursor: pointer; }
  .seg:hover { color: var(--text-body); border-color: var(--accent); }
  .seg.on { color: var(--accent-text); border-color: var(--accent); background: var(--panel); }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  .actions { display: flex; flex-direction: column; gap: 8px; }
  .actions-label { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); margin: 0; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
