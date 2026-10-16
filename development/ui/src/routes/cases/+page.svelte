<script>
  import { onMount } from 'svelte';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Button from '$lib/components/Button.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import TierBadge from '$lib/components/TierBadge.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import EventFeedItem from '$lib/components/EventFeedItem.svelte';
  import AuditRow from '$lib/components/AuditRow.svelte';
  import { EVIDENCE, EVIDENCE_COLUMNS, SELECTED_DETAIL, AUDIT, SEED_FEED, NEW_EVENTS } from '$lib/data.js';
  import { caseCtx, enterCase } from '$lib/case.svelte.js';

  let selectedArtifact = $state('ART-0091');
  let feed = $state([...SEED_FEED]);
  let freshId = $state(null);
  let detail = $derived(SELECTED_DETAIL(selectedArtifact));
  let c = $derived(caseCtx.active);

  onMount(() => {
    let nid = 5, cursor = 0;
    const t = setInterval(() => {
      const tpl = NEW_EVENTS[cursor % NEW_EVENTS.length];
      cursor += 1;
      const id = nid++;
      feed = [{ id, time: new Date().toTimeString().slice(0, 8), ...tpl }, ...feed].slice(0, 40);
      freshId = id;
      setTimeout(() => { if (freshId === id) freshId = null; }, 900);
    }, 3200);
    return () => clearInterval(t);
  });
</script>

<Sidebar selected={c?.caseId} onSelect={(id) => enterCase(id)} />

<main>
  {#if !c}
    <div class="empty">
      <div class="empty-inner">
        <div class="empty-mode">Case mode</div>
        <h1>No case selected</h1>
        <p>Pick a case from the caseload to enter case mode. Everything under Cases then scopes to it, like switching tenant.</p>
      </div>
    </div>
  {:else}
    <div class="case-head">
      <div class="badges">
        <span class="cid">{c.caseId}</span>
        <TierBadge tier={c.tier} />
        <Badge tone="neutral">Active</Badge>
      </div>
      <div class="title-row">
        <h1>{c.title}</h1>
        <div class="actions">
          <Button variant="ghost" size="sm">Export dossier</Button>
          <Button variant="primary" size="sm">Reclassify</Button>
          <Button variant="ghost" size="sm">Seal</Button>
        </div>
      </div>
      <div class="quick">
        <a href="/cases/evidence">Evidence</a>
        <a href="/cases/documents">Documents</a>
        <a href="/cases/attachments">Attachments</a>
        <a href="/cases/logs">Logs</a>
      </div>
    </div>

    <div class="body">
      <div class="col">
        <Panel title="Evidence · indicators & artifacts" class="grow">
          {#snippet action()}<span class="count">{EVIDENCE.length} items</span>{/snippet}
          <DataTable rowKey="id" columns={EVIDENCE_COLUMNS} rows={EVIDENCE}
            selectedId={selectedArtifact} onRowClick={(r) => (selectedArtifact = r.id)} />
        </Panel>
        <Panel title="Audit trail · immutable" class="audit">
          {#each AUDIT as a}<AuditRow {...a} />{/each}
        </Panel>
      </div>
      <div class="col">
        <EvidencePanel title={`Selected · ${selectedArtifact}`} items={detail} />
        <Panel title="Live event feed" class="grow">
          {#snippet action()}<span class="streaming"><span class="dot"></span>STREAMING</span>{/snippet}
          {#each feed as e (e.id)}<EventFeedItem {...e} fresh={e.id === freshId} />{/each}
        </Panel>
      </div>
    </div>
  {/if}
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }

  .empty { flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px; }
  .empty-inner { max-width: 60ch; text-align: center; }
  .empty-mode { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--accent-text); margin-bottom: 8px; }
  .empty-inner h1 { margin: 0 0 8px; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); }
  .empty-inner p { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); line-height: var(--lh-normal); }

  .case-head { flex: 0 0 auto; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .badges { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
  .cid { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .title-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }
  .actions { display: flex; gap: 8px; flex: 0 0 auto; }
  .quick { display: flex; gap: 14px; margin-top: 10px; }
  .quick a { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--accent-text); text-decoration: none; }
  .quick a:hover { text-decoration: underline; }

  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(320px, 1fr); gap: 16px; padding: 16px; overflow: hidden; }
  .col { display: flex; flex-direction: column; gap: 16px; min-height: 0; }
  :global(.panel.grow) { flex: 1; }
  :global(.panel.audit) { flex: 0 0 auto; max-height: 168px; }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .streaming { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 10px; letter-spacing: .1em; color: var(--red-text); }
  .streaming .dot { width: 5px; height: 5px; border-radius: 50%; background: var(--red-text); }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
