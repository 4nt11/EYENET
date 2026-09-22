<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import { linkageTone } from '$lib/data.js';
  import { linkageCtx, linkageView, loadLinkages, loadLinkageDetail, decideLinkage } from '$lib/linkage.svelte.js';

  // Columns are the fields /v1/linkages returns. No `tier` (severity) — the API
  // carries no such field; the pair is UUID-short (handles resolve in detail).
  const COLUMNS = [
    { key: 'idShort', header: 'Linkage', mono: true, width: '96px' },
    { key: 'pair', header: 'Pair', mono: true },
    { key: 'state', header: 'State', badge: true, tone: linkageTone, width: '110px' },
    { key: 'method', header: 'Method', mono: true, width: '120px' },
    { key: 'scoreText', header: 'Score', mono: true, align: 'right', width: '80px' }
  ];

  let selectedId = $state(null);
  let sel = $derived(linkageCtx.list.find((x) => x.id === selectedId) ?? linkageCtx.list[0] ?? null);
  let open = $derived(sel && (sel.state === 'proposed' || sel.state === 'suspected'));
  let pending = $derived(linkageCtx.list.filter((x) => x.state === 'proposed' || x.state === 'suspected').length);

  let reason = $state('');
  let note = $state('');

  // Fetch the selected linkage's evidence + actor handles whenever selection moves.
  $effect(() => {
    if (sel) loadLinkageDetail(sel.id, sel.actorAId, sel.actorBId);
  });

  onMount(loadLinkages);

  async function decide(kind) {
    if (!reason.trim() || !sel) return;
    await decideLinkage(sel.id, kind, reason.trim(), note.trim());
    reason = '';
    note = '';
  }
</script>

<main>
  <SectionHeader group="Investigate" slug="linkages" title="Linkages">
    <span class="pending">{pending} awaiting decision</span>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      {#if linkageCtx.list.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={linkageCtx.list}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !linkageCtx.loaded}Loading…{:else if linkageCtx.error}Could not load linkages: {linkageCtx.error}{:else}No linkages proposed yet.{/if}
        </p>
      {/if}
    </div>

    {#if sel}
      <div class="detail-col">
        <div class="pair-card">
          <div class="pair-head">
            <span class="lid">{sel.id}</span>
            <Badge tone={linkageTone(sel.state)} dot>{sel.state}</Badge>
          </div>
          <div class="pair">
            <a class="chip" href="/actors" title={sel.actorAId}>
              <span class="chandle">{linkageView.handleA ?? sel.actorAId.slice(0, 8)}</span>
              <span class="cid">{sel.actorAId}</span>
            </a>
            <span class="link-glyph">↔</span>
            <a class="chip" href="/actors" title={sel.actorBId}>
              <span class="chandle">{linkageView.handleB ?? sel.actorBId.slice(0, 8)}</span>
              <span class="cid">{sel.actorBId}</span>
            </a>
          </div>
          <div class="meta">
            <span class="m"><span class="k">Method</span> {sel.method || '—'}</span>
            <span class="m"><span class="k">Score</span> {sel.scoreText}</span>
            <span class="m"><span class="k">Proposed</span> {sel.proposedAt}</span>
            {#if sel.decidedAt}<span class="m"><span class="k">Decided</span> {sel.decidedAt} · {sel.decidedBy}</span>{/if}
          </div>
        </div>

        <Panel title="Evidence (comparators)">
          {#each linkageView.evidence as e}
            <div class="erow">
              <span class="ecmp">{e.comparator}</span>
              <span class="escore">{e.score}</span>
              <span class="edetail">{e.detail}</span>
            </div>
          {:else}
            <p class="pnote">{linkageView.loading ? 'Loading…' : 'No comparator evidence recorded.'}</p>
          {/each}
        </Panel>

        <div class="decision">
          <div class="decision-label">Operator decision</div>
          {#if open}
            <input class="field" type="text" bind:value={reason} placeholder="Reason (required)" disabled={linkageView.submitting} />
            <textarea class="field area" rows="2" bind:value={note} placeholder="Note (optional)" disabled={linkageView.submitting}></textarea>
            <div class="actions">
              <Button variant="primary" size="sm" disabled={linkageView.submitting || !reason.trim()} onclick={() => decide('confirm')}>Confirm</Button>
              {#if sel.state === 'proposed'}<Button variant="ghost" size="sm" disabled={linkageView.submitting || !reason.trim()} onclick={() => decide('suspect')}>Suspect</Button>{/if}
              <Button variant="destructive" size="sm" disabled={linkageView.submitting || !reason.trim()} onclick={() => decide('reject')}>Reject</Button>
            </div>
            {#if sel.state === 'suspected'}
              <p class="hint">Suspected by the Verifier. Confirming triggers persona aggregation.</p>
            {/if}
          {:else}
            <p class="settled">{sel.state} {sel.decidedBy ? `by ${sel.decidedBy} ` : ''}{sel.decidedAt ? `at ${sel.decidedAt}` : ''}. Terminal state.</p>
          {/if}
          {#if linkageView.submitMsg}<p class="submitmsg">{linkageView.submitMsg}</p>{/if}
        </div>
      </div>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .pending { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(320px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .pair-card { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 12px; }
  .pair-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .lid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); overflow: hidden; text-overflow: ellipsis; }
  .pair { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .chip { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--surface); text-decoration: none; transition: border-color 120ms ease; }
  .chip:hover { border-color: var(--accent); }
  .chandle { font-family: var(--font-mono); font-size: var(--fs-13); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .cid { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .link-glyph { font-family: var(--font-mono); font-size: var(--fs-16); color: var(--accent-text); }
  .meta { display: flex; flex-wrap: wrap; gap: 14px; }
  .m { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .m .k { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); margin-right: 5px; }

  .erow { display: grid; grid-template-columns: minmax(0, 1.6fr) 60px 1fr; gap: 10px; align-items: baseline; padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .erow:last-child { border-bottom: none; }
  .ecmp { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-secondary); }
  .escore { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); }
  .edetail { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .decision { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
  .decision-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .field { width: 100%; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .field:focus { outline: none; border-color: var(--accent); }
  .field::placeholder { color: var(--text-faint); }
  .field:disabled { opacity: 0.6; }
  .area { resize: vertical; font-family: var(--font-sans); }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .hint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }
  .settled { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }
  .submitmsg { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
