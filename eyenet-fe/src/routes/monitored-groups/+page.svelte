<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Button from '$lib/components/Button.svelte';
  import Dropdown from '$lib/components/Dropdown.svelte';
  import {
    groupCtx, groupView, groupStatusTone, isJoinable, loadGroups, joinGroup, leaveGroup, scanGroups, short,
    stealerCtx, loadStealerChannels, markStealer, GROUP_PAGE_SIZE
  } from '$lib/group.svelte.js';
  import { auth } from '$lib/auth.svelte.js';
  import { collectorCtx, loadCollectors } from '$lib/collector.svelte.js';
  import { sourceCtx, loadSources } from '$lib/source.svelte.js';
  import { PLATFORMS } from '$lib/discovery-shape.js';

  // Resolve a group's source_id -> platform label (the SOURCE's platform, used
  // for the join-collector lease — not the candidate's own platform).
  const srcOf = (sourceId) => sourceCtx.list.find((s) => s.id === sourceId) ?? null;
  const platformOf = (sourceId) => srcOf(sourceId)?.platform ?? short(sourceId);
  // Forum base URL (if the source is a forum) -> host, and the full category URL.
  // Two forums have the SAME category slugs, so the host is the disambiguator.
  const forumHostOf = (sourceId) => {
    const u = srcOf(sourceId)?.forumBaseUrl;
    return u ? u.replace(/^https?:\/\//, '').split('/')[0] : '';
  };
  const urlOf = (sourceId, slug) => {
    const u = srcOf(sourceId)?.forumBaseUrl;
    return u ? `${u.replace(/\/$/, '')}/${slug}` : '';
  };

  const COLUMNS = [
    { key: 'platform', header: 'Platform', mono: true, width: '88px' },
    { key: 'foundVia', header: 'Found via', mono: true, width: '104px' },
    { key: 'kind', header: 'Kind', mono: true, width: '84px' },
    { key: 'title', header: 'Group', mono: true },
    { key: 'forum', header: 'Forum', mono: true, width: '150px' },
    { key: 'status', header: 'Status', badge: true, tone: groupStatusTone, width: '150px' },
    { key: 'lastSeen', header: 'Last seen', mono: true, align: 'right', width: '170px' }
  ];

  // Client-side membership + real-platform filters over the server-narrowed set.
  // realPlatform is derived from the candidate shape (a telegram @handle found on
  // a forum is a telegram lead), so it can't be a server param — filter here.
  let member = $state('all'); // 'all' | 'member' | 'discovered' -> server member_dialog
  let platformFilter = $state(''); // '' | forum | telegram | matrix | discord (client-side)
  let monitoredOnly = $state(false); // server state=joined
  // Platform shows the candidate's REAL platform (its shape), EXCEPT Discord, whose
  // CHANNEL kind is shape-ambiguous with Telegram — resolve those from the source kind
  // (authoritative for a monitored group, which is never a cross-platform lead).
  const rowPlatform = (g) => (srcOf(g.sourceId)?.platform === 'discord' ? 'discord' : g.realPlatform);
  // member + monitored are SERVER-side (member_dialog + state=joined), so counts
  // and pagination are coherent across the whole set. platform is the one axis
  // that can't be a server param — realPlatform is the candidate's SHAPE (a
  // telegram @handle seen on a forum is a telegram lead) — so it refines the
  // current page client-side only. ponytail: page-local platform filter; make it
  // server-side only if an operator actually needs cross-page platform counts.
  const rows = $derived(
    groupCtx.list
      .filter((g) => !platformFilter || rowPlatform(g) === platformFilter)
      .map((g) => ({ ...g, platform: rowPlatform(g), forum: forumHostOf(g.sourceId) || '—' }))
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
          ...(urlOf(sel.sourceId, sel.platformGroupId)
            ? [{ label: 'URL', value: urlOf(sel.sourceId, sel.platformGroupId), mono: true }]
            : []),
          ...(sel.groupId ? [{ label: 'Group id', value: short(sel.groupId) }] : [])
        ]
      : []
  );

  // Server-side narrowing: substring search + source + monitored-status, debounced
  // so each keystroke doesn't hammer the API. Any change resets to page 0.
  let search = $state('');
  let sourceFilter = $state('');
  // The server-side filter set at a given page (member_dialog + state=joined).
  const filterOpts = (page) => ({
    page,
    memberDialog: member === 'all' ? null : member === 'member',
    state: monitoredOnly ? 'joined' : ''
  });
  $effect(() => {
    // Track every server axis; any change debounces a reload back to page 0.
    const s = search, src = sourceFilter, mem = member, mon = monitoredOnly;
    const t = setTimeout(
      () => loadGroups(s, src, { page: 0, memberDialog: mem === 'all' ? null : mem === 'member', state: mon ? 'joined' : '' }),
      250
    );
    return () => clearTimeout(t);
  });

  // Numbered server-side pagination. pageCount from the estimated total; pager is
  // the compact token list (first, a window around current, last, with … gaps).
  const goPage = (p) => loadGroups(search, sourceFilter, filterOpts(p));
  const pageCount = $derived(
    groupCtx.total == null ? 1 : Math.max(1, Math.ceil(groupCtx.total / GROUP_PAGE_SIZE))
  );
  function pageTokens(cur, count) {
    if (count <= 1) return [0];
    const keep = [...new Set([0, count - 1, cur, Math.max(0, cur - 1), Math.min(count - 1, cur + 1)])]
      .filter((p) => p >= 0 && p < count).sort((a, b) => a - b);
    const out = [];
    for (let i = 0; i < keep.length; i++) {
      if (i > 0 && keep[i] - keep[i - 1] > 1) out.push('…');
      out.push(keep[i]);
    }
    return out;
  }
  const pager = $derived(pageTokens(groupCtx.page, pageCount));

  // Styled-dropdown option lists ({ v, l }).
  const sourceOpts = $derived([
    { v: '', l: 'All sources' },
    ...sourceCtx.list.map((s) => ({ v: s.id, l: `${s.name} · ${s.platform}` }))
  ]);
  const platformOpts = [{ v: '', l: 'All platforms' }, ...PLATFORMS.map((p) => ({ v: p, l: p }))];

  onMount(() => {
    loadCollectors();
    loadSources();
    loadStealerChannels();
  });

  let backfillOnJoin = $state(true);

  // Stealer-channel marking: admin:stealer to mark, read:stealer to see the set.
  // Only a real (joined) group has a groupId to POST the category to.
  const canMarkStealer = $derived(auth.user?.scopes?.includes('admin:stealer') ?? false);
  const isStealer = $derived(!!sel?.groupId && stealerCtx.ids.includes(sel.groupId));

  async function join() {
    if (!sel || !collectorId) return;
    await joinGroup(sel.id, collectorId, backfillOnJoin);
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
        <Dropdown options={sourceOpts} bind:value={sourceFilter} minWidth="190px" />
        <Dropdown options={platformOpts} bind:value={platformFilter} minWidth="124px" />
        <div class="segs">
          <button class="seg" class:on={member === 'all'} onclick={() => (member = 'all')}>All</button>
          <button class="seg" class:on={member === 'discovered'} onclick={() => (member = 'discovered')}>Discovered</button>
          <button class="seg" class:on={member === 'member'} onclick={() => (member = 'member')}>Already a member</button>
        </div>
        <button class="seg" class:on={monitoredOnly} onclick={() => (monitoredOnly = !monitoredOnly)}
          title="Show only joined-and-monitored groups">Monitored only</button>
        {#if groupCtx.total != null}<span class="count">{groupCtx.total.toLocaleString()} match{groupCtx.total === 1 ? '' : 'es'}</span>{/if}
      </div>
      <div class="table-scroll">
      {#if rows.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={rows} stickyHead stickyTop="0"
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !groupCtx.loaded}Loading…{:else if groupCtx.error}Could not load groups: {groupCtx.error}{:else if groupCtx.list.length}No groups in this view.{:else if search.trim() || sourceFilter}No groups match the current filters.{:else}No groups visible yet. Run a collector (it scans its identity's groups on start), or Rescan.{/if}
        </p>
      {/if}
      </div>
      {#if pageCount > 1}
        <nav class="pager" aria-label="Group pages">
          <button class="seg" disabled={groupCtx.page === 0} onclick={() => goPage(groupCtx.page - 1)}>Prev</button>
          {#each pager as p}
            {#if p === '…'}
              <span class="gap">…</span>
            {:else}
              <button class="seg" class:on={p === groupCtx.page} onclick={() => goPage(p)}>{p + 1}</button>
            {/if}
          {/each}
          <button class="seg" disabled={groupCtx.page >= pageCount - 1} onclick={() => goPage(groupCtx.page + 1)}>Next</button>
        </nav>
      {/if}
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
            <label class="backfill-opt">
              <input type="checkbox" bind:checked={backfillOnJoin} />
              Backfill full history on join
              <span class="sub">uncheck for very large groups (429 risk)</span>
            </label>
            <Button variant="primary" size="sm" disabled={groupView.submitting || !collectorId} onclick={join}>Join group</Button>
          {:else if sel.status === 'monitored'}
            <Button variant="destructive" size="sm" disabled={groupView.submitting} onclick={leave}>Leave group</Button>
          {:else}
            <span class="hint">This group is {sel.status}; no action.</span>
          {/if}
          {#if canMarkStealer && sel.groupId}
            <label class="backfill-opt">
              <input type="checkbox" checked={isStealer} disabled={groupView.submitting}
                onchange={(e) => {
                  const on = e.currentTarget.checked;
                  if (window.confirm(`${on ? 'Mark' : 'Unmark'} "${sel.title}" as a stealer-log channel?`)) {
                    markStealer(sel.groupId, on);
                  } else {
                    e.currentTarget.checked = isStealer; // cancelled — revert the box
                  }
                }} />
              Stealer-log channel
              <span class="sub">bypasses the attachment size cap — captures the multi-GB archive drops</span>
            </label>
          {:else if canMarkStealer}
            <span class="hint">Join this group first to mark it a stealer channel.</span>
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
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 2.2fr) minmax(300px, 0.85fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; display: flex; flex-direction: column; gap: 10px; }
  .table-scroll { flex: 1; min-height: 0; overflow: auto; }
  .filter-bar { display: flex; gap: 8px; flex-shrink: 0; flex-wrap: wrap; align-items: center; }
  .segs { display: flex; gap: 6px; }
  .search { flex: 1 1 220px; min-width: 160px; box-sizing: border-box; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .search::placeholder { color: var(--text-faint); }
  .seg { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 5px 10px; cursor: pointer; }
  .seg:hover { color: var(--text-body); border-color: var(--accent); }
  .seg.on { color: var(--accent-text); border-color: var(--accent); background: var(--panel); }
  .seg:disabled { opacity: 0.4; cursor: default; color: var(--text-secondary); border-color: var(--border-strong); }
  .pager { display: flex; gap: 6px; flex-shrink: 0; flex-wrap: wrap; align-items: center; padding-top: 2px; }
  .pager .gap { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); padding: 0 2px; }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); white-space: nowrap; align-self: center; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  .actions { display: flex; flex-direction: column; gap: 8px; }
  .actions-label { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); margin: 0; }
  .backfill-opt { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-secondary); cursor: pointer; }
  .backfill-opt input { cursor: pointer; }
  .backfill-opt .sub { flex-basis: 100%; padding-left: 22px; font-size: var(--fs-11); color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
