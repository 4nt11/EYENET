<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import TierBadge from '$lib/components/TierBadge.svelte';
  import Button from '$lib/components/Button.svelte';
  import {
    attachmentCtx, attachmentView, tierTone,
    loadAttachments, loadAttachmentManifest
  } from '$lib/attachment.svelte.js';

  const COLUMNS = [
    { key: 'idShort', header: 'Blob', mono: true, width: '96px' },
    { key: 'filename', header: 'File', mono: true },
    { key: 'mime', header: 'MIME', mono: true, width: '150px' },
    { key: 'tier', header: 'Tier', badge: true, tone: tierTone, width: '110px' }
  ];

  let selectedId = $state(null);
  let a = $derived(attachmentCtx.list.find((x) => x.id === selectedId) ?? attachmentCtx.list[0] ?? null);

  // Base metadata is on the row; the manifest adds source-subject + collected-at.
  let detail = $derived(
    a
      ? [
          { label: 'Blob', value: a.id },
          { label: 'SHA-256', value: a.sha256 },
          { label: 'MIME', value: a.mime },
          { label: 'Size', value: `${a.sizeBytes.toLocaleString()} bytes` },
          { label: 'Kind', value: a.kind },
          { label: 'Message', value: a.messageId },
          ...(attachmentView.manifest
            ? [
                {
                  label: 'Source',
                  value: `${attachmentView.manifest.source_subject_kind} · ${attachmentView.manifest.source_subject_id}`
                },
                { label: 'Collected', value: attachmentView.manifest.collected_at }
              ]
            : [])
        ]
      : []
  );

  $effect(() => {
    if (a) loadAttachmentManifest(a.id);
  });

  onMount(loadAttachments);
</script>

<main>
  <SectionHeader group="Cases" slug="attachments" title="Attachments" />

  <div class="body">
    <div class="table-col">
      {#if attachmentCtx.list.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={attachmentCtx.list}
          selectedId={a?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !attachmentCtx.loaded}Loading…{:else if attachmentCtx.error}Could not load attachments: {attachmentCtx.error}{:else}No attachments collected yet.{/if}
        </p>
      {/if}
    </div>

    {#if a}
      <div class="detail-col">
        <div class="dhead">
          <div class="dtitle"><span class="dfile">{a.filename}</span><TierBadge tier={a.classifierTier} effective={a.tier} /></div>
          <Button variant="ghost" size="sm" disabled>Reclassify</Button>
        </div>

        <EvidencePanel title="Manifest" items={detail} labelWidth={100} />
        {#if attachmentView.error}<p class="pnote">{attachmentView.error}</p>{/if}

        <Panel title="Bytes">
          <div class="gate">
            <p>Bytes are served only after a signed acknowledgment is journaled.</p>
            <Button variant="primary" size="sm" disabled>Request access</Button>
            <p class="defer">Signed byte access requires operator signing (M9.B2) — not yet wired.</p>
          </div>
        </Panel>

        <Panel title="Access journal">
          <div class="empty">The file-access journal reader ships with the signed-access work (M9.B2). An exoneration query would return a signed non-access assertion.</div>
        </Panel>
      </div>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(340px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 14px; min-height: 0; overflow: auto; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .dhead { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .dtitle { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .dfile { font-family: var(--font-mono); font-size: var(--fs-14); letter-spacing: var(--tracking-data); color: var(--text); }

  .gate { padding: 20px; display: flex; flex-direction: column; gap: 12px; align-items: flex-start; }
  .gate p { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }
  .defer { font-size: var(--fs-12); color: var(--text-faint); }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); line-height: var(--lh-normal); }

  @media (max-width: 940px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
