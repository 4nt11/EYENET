<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import {
    candidateCtx, candidateView, candidateTone,
    loadCandidates, loadCandidateDetail,
    approveCandidate, rejectCandidate, parkCandidate, retryCandidate
  } from '$lib/candidate.svelte.js';
  import { collectorCtx, loadCollectors } from '$lib/collector.svelte.js';
  import { sourceCtx, loadSources } from '$lib/source.svelte.js';

  // Columns are fields /v1/candidates returns. Platform is dropped from the list
  // (needs a per-row source join — never fabricate) and shown in detail after a
  // single source fetch. No `tier`/severity — the API carries no such field.
  const COLUMNS = [
    { key: 'idShort', header: 'Candidate', mono: true, width: '96px' },
    { key: 'group', header: 'Group', mono: true },
    { key: 'state', header: 'State', badge: true, tone: candidateTone, width: '110px' },
    { key: 'scoreText', header: 'Score', mono: true, align: 'right', width: '80px' }
  ];

  // `memberDialog` = the operator's own account already sits in this group (seen
  // directly in an identity's dialogs/rooms), vs reachable only via mention
  // descent. Same signal /v1/groups derives `member_unmonitored` from — NOT the
  // candidate `state`, which is collector-lifecycle and says nothing about
  // whether YOU are in it.
  let filter = $state('all'); // 'all' | 'member' | 'discovered'
  let rows = $derived(
    filter === 'all'
      ? candidateCtx.list
      : candidateCtx.list.filter((x) => (filter === 'member' ? x.memberDialog : !x.memberDialog))
  );
  let memberCount = $derived(candidateCtx.list.filter((x) => x.memberDialog).length);

  // Server-side narrowing: substring search + source filter, debounced. The
  // member segments above filter client-side on the already-narrowed set.
  let search = $state('');
  let sourceFilter = $state('');
  $effect(() => {
    const s = search, src = sourceFilter;
    const t = setTimeout(() => loadCandidates(s, src), 250);
    return () => clearTimeout(t);
  });

  let selectedId = $state(null);
  let sel = $derived(rows.find((x) => x.id === selectedId) ?? rows[0] ?? null);
  // Only `queued` (approve/reject) and `joined` (park) carry an operator action.
  let canDecide = $derived(sel?.state === 'queued');
  let canPark = $derived(sel?.state === 'joined');
  // `failed` (a rejected/errored join) can be retried: failed → queued. The
  // endpoint is admin:candidates-gated (grant-only) — a caller without the grant
  // gets a surfaced 403 rather than a hidden button.
  let canRetry = $derived(sel?.state === 'failed');
  // Awaiting an operator OR an automatic flip (requested → joined).
  let pending = $derived(candidateCtx.list.filter((x) => x.state === 'queued' || x.state === 'requested').length);

  let collectorId = $state('');
  let reason = $state('');

  $effect(() => {
    if (sel) loadCandidateDetail(sel.id, sel.sourceId);
  });

  onMount(() => {
    // candidates load via the debounced $effect (initial empty search = all)
    loadCollectors(); // populates the approve → assigned-collector selector
    loadSources(); // populates the source filter dropdown
  });

  async function approve() {
    if (!sel || !collectorId) return;
    await approveCandidate(sel.id, sel.sourceId, collectorId);
    collectorId = '';
  }
  async function reject() {
    if (!sel || !reason.trim()) return;
    await rejectCandidate(sel.id, sel.sourceId, reason.trim());
    reason = '';
  }
  async function park() {
    if (!sel || !reason.trim()) return;
    await parkCandidate(sel.id, sel.sourceId, reason.trim());
    reason = '';
  }
  async function retry() {
    if (!sel) return;
    await retryCandidate(sel.id, sel.sourceId);
  }
</script>

<main>
  <SectionHeader group="Discovery" slug="candidates" title="Candidate triage">
    <span class="pending">{pending} awaiting decision</span>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      <div class="filter-bar">
        <input class="search" type="search" placeholder="Search by name or platform id…"
          bind:value={search} aria-label="Search candidates" />
        <select class="source-sel" bind:value={sourceFilter} aria-label="Filter by source">
          <option value="">All sources</option>
          {#each sourceCtx.list as s}<option value={s.id}>{s.name} · {s.platform}</option>{/each}
        </select>
        <div class="segs">
          <button class="seg" class:on={filter === 'all'} onclick={() => (filter = 'all')}>All · {candidateCtx.list.length}</button>
          <button class="seg" class:on={filter === 'discovered'} onclick={() => (filter = 'discovered')}>Discovered · {candidateCtx.list.length - memberCount}</button>
          <button class="seg" class:on={filter === 'member'} onclick={() => (filter = 'member')}>Already a member · {memberCount}</button>
        </div>
      </div>
      <div class="table-scroll">
      {#if rows.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={rows}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !candidateCtx.loaded}Loading…{:else if candidateCtx.error}Could not load candidates: {candidateCtx.error}{:else if candidateCtx.list.length}No candidates in this view.{:else}No candidates discovered yet.{/if}
        </p>
      {/if}
      </div>
    </div>

    {#if sel}
      <div class="detail-col">
        <div class="card">
          <div class="card-head">
            <span class="cid">{sel.id}</span>
            <Badge tone={candidateTone(sel.state)} dot>{sel.state}</Badge>
          </div>
          <div class="meta">
            <span class="m"><span class="k">Group</span> {sel.group}</span>
            <span class="m"><span class="k">Platform</span> {candidateView.source ?? sel.sourceId.slice(0, 8)}</span>
            <span class="m"><span class="k">Membership</span> {sel.memberDialog ? 'account is a member' : 'discovered (not joined)'}</span>
            {#if sel.kindHint}<span class="m"><span class="k">Kind</span> {sel.kindHint}</span>{/if}
            <span class="m"><span class="k">Group ID</span> {sel.platformGroupId}</span>
            <span class="m"><span class="k">Score</span> {sel.scoreText}</span>
            <span class="m"><span class="k">First seen</span> {sel.firstObserved}</span>
            <span class="m"><span class="k">Last seen</span> {sel.lastObserved}</span>
            {#if candidateView.reviewedBy}<span class="m"><span class="k">Reviewed</span> {candidateView.reviewedBy}{candidateView.reviewedAt ? ` · ${candidateView.reviewedAt}` : ''}</span>{/if}
            {#if candidateView.assignedCollector}<span class="m"><span class="k">Collector</span> {candidateView.assignedCollector}</span>{/if}
            {#if candidateView.resultingGroup}<span class="m"><span class="k">Group row</span> {candidateView.resultingGroup}</span>{/if}
            {#if candidateView.rejectionReason}<span class="m"><span class="k">Rejected</span> {candidateView.rejectionReason}</span>{/if}
          </div>
        </div>

        {#if candidateView.breakdown.length}
          <Panel title="Score breakdown">
            {#each candidateView.breakdown as b}
              <div class="brow"><span class="bk">{b.k}</span><span class="bv">{b.v}</span></div>
            {/each}
          </Panel>
        {/if}

        <Panel title="Mentions (provenance)">
          {#each candidateView.mentions as m}
            <div class="mrow">
              <span class="mkind">{m.kind}</span>
              <span class="mactor">{m.actor}{m.role ? ` · ${m.role}` : ''}</span>
              <span class="mdepth">depth {m.depth}</span>
              <span class="mev">{m.evidence}</span>
            </div>
          {:else}
            <p class="pnote">{candidateView.loading ? 'Loading…' : 'No mentions recorded.'}</p>
          {/each}
        </Panel>

        <div class="decision">
          <div class="decision-label">Triage</div>
          {#if canDecide}
            <label class="fl">
              <span class="fk">Assign collector</span>
              <select class="field" bind:value={collectorId} disabled={candidateView.submitting}>
                <option value="">Select a collector…</option>
                {#each collectorCtx.list as c}
                  <option value={c.id}>{c.name} · {c.kind} · {c.id.slice(0, 8)}</option>
                {/each}
              </select>
            </label>
            <input class="field" type="text" bind:value={reason} placeholder="Reason (reject only)" disabled={candidateView.submitting} />
            <div class="actions">
              <Button variant="primary" size="sm" disabled={candidateView.submitting || !collectorId} onclick={approve}>Approve</Button>
              <Button variant="destructive" size="sm" disabled={candidateView.submitting || !reason.trim()} onclick={reject}>Reject</Button>
            </div>
            {#if !collectorCtx.list.length}<p class="hint">No collectors available to assign · create one under Collectors first.</p>{/if}
          {:else if canPark}
            <input class="field" type="text" bind:value={reason} placeholder="Reason (required)" disabled={candidateView.submitting} />
            <div class="actions">
              <Button variant="ghost" size="sm" disabled={candidateView.submitting || !reason.trim()} onclick={park}>Park</Button>
            </div>
            <p class="hint">Joined group · parking stops further collection on it.</p>
          {:else if canRetry}
            <div class="actions">
              <Button variant="ghost" size="sm" disabled={candidateView.submitting} onclick={retry}>Retry</Button>
            </div>
            <p class="hint">Failed join · retry re-queues it (failed → queued). Needs admin:candidates — retrying can burn identities.</p>
          {:else if sel.state === 'requested'}
            <p class="settled">Approval-gated join (invite-link). Flips REQUESTED → JOINED automatically once membership is confirmed — no operator action.</p>
          {:else if sel.state === 'discovered'}
            <p class="settled">Discovered · awaiting automatic promotion to the queue (score threshold). No operator action yet.</p>
          {:else}
            <p class="settled">{sel.state}. No operator action available.</p>
          {/if}
          {#if candidateView.submitMsg}<p class="submitmsg">{candidateView.submitMsg}</p>{/if}
        </div>
      </div>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .pending { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(320px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; display: flex; flex-direction: column; gap: 10px; }
  .table-scroll { flex: 1; min-height: 0; overflow: auto; }
  .filter-bar { display: flex; gap: 8px; flex-shrink: 0; flex-wrap: wrap; align-items: center; }
  .segs { display: flex; gap: 6px; }
  .search { flex: 1 1 220px; min-width: 160px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .search::placeholder { color: var(--text-faint); }
  .source-sel { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 10px; max-width: 220px; }
  .source-sel:focus { outline: none; border-color: var(--accent); }
  .seg { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 5px 10px; cursor: pointer; }
  .seg:hover { color: var(--text-body); border-color: var(--accent); }
  .seg.on { color: var(--accent-text); border-color: var(--accent); background: var(--panel); }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .card { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 12px; }
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .cid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); overflow: hidden; text-overflow: ellipsis; }
  .meta { display: flex; flex-wrap: wrap; gap: 14px; }
  .m { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .m .k { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); margin-right: 5px; }

  .brow { display: flex; justify-content: space-between; gap: 10px; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .brow:last-child { border-bottom: none; }
  .bk { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); }
  .bv { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); }

  .mrow { display: grid; grid-template-columns: 90px minmax(0, 1.2fr) 72px 1fr; gap: 10px; align-items: baseline; padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .mrow:last-child { border-bottom: none; }
  .mkind { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); }
  .mactor { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-body); }
  .mdepth { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .mev { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; }

  .decision { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .decision-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .fl { display: flex; flex-direction: column; gap: 5px; }
  .fk { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .field { width: 100%; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .field:focus { outline: none; border-color: var(--accent); }
  .field::placeholder { color: var(--text-faint); }
  .field:disabled { opacity: 0.6; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .hint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }
  .settled { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); line-height: var(--lh-normal); }
  .submitmsg { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
