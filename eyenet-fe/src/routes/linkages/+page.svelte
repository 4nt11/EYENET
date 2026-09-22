<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import { LINKAGES, LINKAGE_COLUMNS, linkageTone } from '$lib/data.js';

  let selectedId = $state(LINKAGES[0].linkage_id);
  let l = $derived(LINKAGES.find((x) => x.linkage_id === selectedId) ?? LINKAGES[0]);
  const open = $derived(l.state === 'proposed' || l.state === 'suspected');
  const pending = LINKAGES.filter((x) => x.state === 'proposed' || x.state === 'suspected').length;
  const tierDot = (t) => (t === 'critical' ? 'var(--red)' : t === 'high' ? 'var(--accent)' : 'var(--border-strong)');
</script>

<main>
  <SectionHeader group="Investigate" slug="linkages" title="Linkages">
    <span class="pending">{pending} awaiting decision</span>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      <DataTable rowKey="linkage_id" columns={LINKAGE_COLUMNS} rows={LINKAGES}
        selectedId={selectedId} onRowClick={(r) => (selectedId = r.linkage_id)} />
    </div>

    <div class="detail-col">
      <!-- Pair -->
      <div class="pair-card">
        <div class="pair-head">
          <span class="lid">{l.linkage_id}</span>
          <Badge tone={linkageTone(l.state)} dot>{l.state}</Badge>
        </div>
        <div class="pair">
          <a class="chip" href="/actors" title={l.actor_a.id}>
            <span class="dot" style="background:{tierDot(l.actor_a.tier)}"></span>
            <span class="chandle">{l.actor_a.handle}</span>
            <span class="cid">{l.actor_a.id}</span>
          </a>
          <span class="link-glyph">↔</span>
          <a class="chip" href="/actors" title={l.actor_b.id}>
            <span class="dot" style="background:{tierDot(l.actor_b.tier)}"></span>
            <span class="chandle">{l.actor_b.handle}</span>
            <span class="cid">{l.actor_b.id}</span>
          </a>
        </div>
        <div class="meta">
          <span class="m"><span class="k">Method</span> {l.method}</span>
          <span class="m"><span class="k">Score</span> {l.score.toFixed(2)}</span>
          <span class="m"><span class="k">Proposed</span> {l.proposed_at}</span>
          {#if l.decided_at}<span class="m"><span class="k">Decided</span> {l.decided_at} · {l.decided_by}</span>{/if}
        </div>
      </div>

      <Panel title="Evidence (comparators)">
        {#each l.evidence as e}
          <div class="erow">
            <span class="ecmp">{e.comparator}</span>
            <span class="escore">{e.score.toFixed(2)}</span>
            <span class="edetail">{e.detail}</span>
          </div>
        {/each}
      </Panel>

      <div class="decision">
        <div class="decision-label">Operator decision</div>
        {#if open}
          <input class="field" type="text" placeholder="Reason (required)" />
          <textarea class="field area" rows="2" placeholder="Note (optional)"></textarea>
          <div class="actions">
            <Button variant="primary" size="sm">Confirm</Button>
            {#if l.state === 'proposed'}<Button variant="ghost" size="sm">Suspect</Button>{/if}
            <Button variant="destructive" size="sm">Reject</Button>
          </div>
          {#if l.state === 'suspected'}
            <p class="hint">Suspected by the Verifier. Confirming triggers persona aggregation.</p>
          {/if}
        {:else}
          <p class="settled">{l.state === 'confirmed' ? 'Confirmed' : l.state === 'rejected' ? 'Rejected' : l.state} by {l.decided_by} at {l.decided_at}. Terminal state.</p>
        {/if}
      </div>
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .pending { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); }

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(320px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }

  .pair-card { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); padding: 14px; display: flex; flex-direction: column; gap: 12px; }
  .pair-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .lid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); }
  .pair { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .chip { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: var(--surface); text-decoration: none; transition: border-color 120ms ease; }
  .chip:hover { border-color: var(--accent); }
  .dot { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 auto; }
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
  .area { resize: vertical; font-family: var(--font-sans); }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .hint { margin: 0; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }
  .settled { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
