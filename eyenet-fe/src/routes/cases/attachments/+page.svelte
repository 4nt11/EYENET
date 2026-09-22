<script>
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import AccessDialog from '$lib/components/AccessDialog.svelte';
  import ReclassifyDialog from '$lib/components/ReclassifyDialog.svelte';
  import TierBadge from '$lib/components/TierBadge.svelte';
  import Button from '$lib/components/Button.svelte';
  import { ATTACHMENTS, ATT_COLUMNS, ACCESS_LOG } from '$lib/data.js';

  let selectedId = $state(ATTACHMENTS[0].blob_id);
  let a = $derived(ATTACHMENTS.find((x) => x.blob_id === selectedId) ?? ATTACHMENTS[0]);
  let granted = $state(false);
  let accessOpen = $state(false);
  let reclassOpen = $state(false);

  $effect(() => { selectedId; granted = false; });

  const log = $derived(ACCESS_LOG.filter((r) => r.blob_id === selectedId));
  const isImage = $derived(a.content_mime.startsWith('image/'));
  const manifestOf = $derived({ tier: a.tier, content_mime: a.content_mime, content_size: a.content_size, content_hash: a.content_hash });
  const subjectOf = $derived({ id: a.blob_id, kind: 'attachment', classifier_tier: a.classifier_tier, effective_tier: a.tier });

  let detail = $derived([
    { label: 'Blob', value: a.blob_id },
    { label: 'SHA-256', value: a.content_hash },
    { label: 'MIME', value: a.content_mime },
    { label: 'Size', value: `${a.content_size.toLocaleString()} bytes` },
    { label: 'Source', value: `${a.source_subject_kind} · ${a.source_subject_id}` },
    { label: 'Collected', value: a.collected_at }
  ]);
</script>

<main>
  <SectionHeader group="Cases" slug="attachments" title="Attachments" />

  <div class="body">
    <div class="table-col">
      <DataTable rowKey="blob_id" columns={ATT_COLUMNS} rows={ATTACHMENTS}
        selectedId={selectedId} onRowClick={(r) => (selectedId = r.blob_id)} />
    </div>

    <div class="detail-col">
      <div class="dhead">
        <div class="dtitle"><span class="dfile">{a.filename}</span><TierBadge tier={a.classifier_tier} effective={a.tier} /></div>
        <Button variant="ghost" size="sm" onclick={() => (reclassOpen = true)}>Reclassify</Button>
      </div>

      <EvidencePanel title="Manifest" items={detail} labelWidth={100} />

      <Panel title="Bytes">
        {#if granted}
          <div class="bytes">
            {#if isImage}
              <div class="imgph">image bytes served · rendered inline (mock)</div>
            {:else}
              <div class="hexph">byte / hex view mounts here · {a.content_size.toLocaleString()} bytes served (mock)</div>
            {/if}
          </div>
        {:else}
          <div class="gate">
            <p>Bytes are served only after a signed acknowledgment is journaled.</p>
            <Button variant="primary" size="sm" onclick={() => (accessOpen = true)}>Request access</Button>
          </div>
        {/if}
      </Panel>

      <Panel title="Access journal">
        {#if log.length}
          {#each log as e}
            <div class="lrow">
              <span class="lts">{e.served_at}</span>
              <span class="luser">{e.user}</span>
              <span class="lvia">{e.served_via}</span>
              <span class="lreq">{e.request_id}</span>
            </div>
          {/each}
        {:else}
          <div class="empty">No recorded accesses. An exoneration query would return a signed non-access assertion.</div>
        {/if}
      </Panel>
    </div>
  </div>
</main>

<AccessDialog bind:open={accessOpen} manifest={manifestOf} onconfirm={() => (granted = true)} />
<ReclassifyDialog bind:open={reclassOpen} subject={subjectOf} onconfirm={(r) => console.log('reclassify', r)} />

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(340px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 14px; min-height: 0; overflow: auto; }

  .dhead { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .dtitle { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .dfile { font-family: var(--font-mono); font-size: var(--fs-14); letter-spacing: var(--tracking-data); color: var(--text); }

  .gate { padding: 20px; display: flex; flex-direction: column; gap: 12px; align-items: flex-start; }
  .gate p { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }
  .bytes { padding: 16px; }
  .imgph, .hexph { border: 1px dashed var(--border-strong); border-radius: var(--radius); padding: 28px; text-align: center; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .lrow { display: grid; grid-template-columns: 160px 90px 150px 1fr; gap: 10px; align-items: baseline; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .lrow:last-child { border-bottom: none; }
  .lts { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .luser { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); }
  .lvia { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); }
  .lreq { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); text-align: right; }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }

  @media (max-width: 940px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
