<script>
  import { onMount } from 'svelte';
  import { Tabs } from 'bits-ui';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidenceViewer from '$lib/components/EvidenceViewer.svelte';
  import FindingsList from '$lib/components/FindingsList.svelte';
  import TierBadge from '$lib/components/TierBadge.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import {
    documentCtx, documentView, tierTone,
    loadDocuments, loadDocumentManifest
  } from '$lib/document.svelte.js';

  // Columns map GET /v1/documents rows. `tier` is the effective sensitivity;
  // there is no severity field (that mock concept has no API backing).
  const COLUMNS = [
    { key: 'idShort', header: 'Document', mono: true, width: '96px' },
    { key: 'filename', header: 'File', mono: true },
    { key: 'docKind', header: 'Kind', mono: true, width: '90px' },
    { key: 'tier', header: 'Tier', badge: true, tone: tierTone, width: '110px' },
    { key: 'uploaded', header: 'Uploaded', mono: true, align: 'right', width: '150px' }
  ];

  let selectedId = $state(null);
  let d = $derived(documentCtx.list.find((x) => x.id === selectedId) ?? documentCtx.list[0] ?? null);
  let tab = $state('findings');

  // Fetch the manifest (redacted classification for FindingsList) on selection.
  $effect(() => {
    if (d) loadDocumentManifest(d.id);
  });

  onMount(loadDocuments);
</script>

<main>
  <SectionHeader group="Cases" slug="documents" title="Documents" />

  <div class="body">
    <div class="table-col">
      {#if documentCtx.list.length}
        <DataTable rowKey="id" columns={COLUMNS} rows={documentCtx.list}
          selectedId={d?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !documentCtx.loaded}Loading…{:else if documentCtx.error}Could not load documents: {documentCtx.error}{:else}No documents ingested yet.{/if}
        </p>
      {/if}
    </div>

    {#if d}
      <div class="detail-col">
        <div class="dhead">
          <div class="dtitle">
            <span class="dfile">{d.filename}</span>
            <TierBadge tier={d.classifierTier} effective={d.tier} />
            {#if d.reviewRequired}<Badge tone="high" dot>review</Badge>{/if}
          </div>
          <div class="dactions">
            <Button variant="ghost" size="sm" disabled>Reclassify</Button>
          </div>
        </div>

        <div class="viewer">
          <EvidenceViewer bind:value={tab}
            tabs={[{ value: 'text', label: 'Extracted text' }, { value: 'findings', label: 'Findings' }, { value: 'metadata', label: 'Metadata' }]}>
            <Tabs.Content value="text">
              <div class="gate">
                <p>Extracted text is served through the signed, journaled access step.</p>
                <Button variant="primary" size="sm" disabled>Request access</Button>
                <p class="defer">Signed byte access requires operator signing (M9.B2) — not yet wired.</p>
              </div>
            </Tabs.Content>
            <Tabs.Content value="findings">
              {#if documentView.loading}
                <p class="pnote">Loading classification…</p>
              {:else if documentView.error}
                <p class="pnote">{documentView.error}</p>
              {:else if documentView.manifest}
                <FindingsList classification={documentView.manifest.classification} />
              {:else}
                <p class="pnote">No classification record.</p>
              {/if}
            </Tabs.Content>
            <Tabs.Content value="metadata">
              <div class="meta">
                <div class="mrow"><span class="k">Document</span><span class="v">{d.id}</span></div>
                <div class="mrow"><span class="k">SHA-256</span><span class="v hash">{d.sha256}</span></div>
                <div class="mrow"><span class="k">MIME</span><span class="v">{d.mime}</span></div>
                <div class="mrow"><span class="k">Kind</span><span class="v">{d.docKind || '—'}</span></div>
                <div class="mrow"><span class="k">Size</span><span class="v">{d.sizeBytes.toLocaleString()} bytes</span></div>
                <div class="mrow"><span class="k">Uploaded</span><span class="v">{d.uploaded}</span></div>
                <div class="mrow"><span class="k">Ingested</span><span class="v">{d.ingested}</span></div>
              </div>
            </Tabs.Content>
          </EvidenceViewer>
        </div>
      </div>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(360px, 1.2fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }

  .dhead { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .dtitle { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .dfile { font-family: var(--font-mono); font-size: var(--fs-14); letter-spacing: var(--tracking-data); color: var(--text); }

  .viewer { flex: 1; min-height: 0; display: flex; }
  .gate { padding: 24px; display: flex; flex-direction: column; gap: 12px; align-items: flex-start; }
  .gate p { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }
  .defer { font-size: var(--fs-12); color: var(--text-faint); }

  .meta { padding: 4px 0; }
  .mrow { display: grid; grid-template-columns: 110px 1fr; gap: 12px; align-items: baseline; padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .mrow:last-child { border-bottom: none; }
  .k { font-family: var(--font-sans); font-size: var(--fs-12); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .v { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .v.hash { overflow-wrap: anywhere; color: var(--text-muted); }

  @media (max-width: 940px) { .body { grid-template-columns: 1fr; overflow: auto; } .viewer { min-height: 340px; } }
</style>
