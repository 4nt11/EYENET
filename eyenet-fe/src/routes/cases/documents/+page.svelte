<script>
  import { Tabs } from 'bits-ui';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidenceViewer from '$lib/components/EvidenceViewer.svelte';
  import FindingsList from '$lib/components/FindingsList.svelte';
  import CodeBlock from '$lib/components/CodeBlock.svelte';
  import AccessDialog from '$lib/components/AccessDialog.svelte';
  import ReclassifyDialog from '$lib/components/ReclassifyDialog.svelte';
  import TierBadge from '$lib/components/TierBadge.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import Button from '$lib/components/Button.svelte';
  import { DOCUMENTS, DOC_COLUMNS } from '$lib/data.js';

  let selectedId = $state(DOCUMENTS[0].document_id);
  let d = $derived(DOCUMENTS.find((x) => x.document_id === selectedId) ?? DOCUMENTS[0]);
  let tab = $state('findings');
  let granted = $state(false);
  let accessOpen = $state(false);
  let reclassOpen = $state(false);

  // Reset the signed-access grant when switching documents.
  $effect(() => { selectedId; granted = false; tab = 'findings'; });

  const manifestOf = $derived({ tier: d.tier, content_mime: d.content_mime, content_size: d.content_size, content_hash: d.content_hash });
  const subjectOf = $derived({ id: d.document_id, kind: 'document', classifier_tier: d.classifier_tier, effective_tier: d.tier });
</script>

<main>
  <SectionHeader group="Cases" slug="documents" title="Documents">
    <Button variant="ghost" size="sm">Upload</Button>
  </SectionHeader>

  <div class="body">
    <div class="table-col">
      <DataTable rowKey="document_id" columns={DOC_COLUMNS} rows={DOCUMENTS}
        selectedId={selectedId} onRowClick={(r) => (selectedId = r.document_id)} />
    </div>

    <div class="detail-col">
      <div class="dhead">
        <div class="dtitle">
          <span class="dfile">{d.filename}</span>
          <TierBadge tier={d.classifier_tier} effective={d.tier} />
          {#if d.review_required}<Badge tone="high" dot>review</Badge>{/if}
        </div>
        <div class="dactions">
          <Button variant="ghost" size="sm" onclick={() => (reclassOpen = true)}>Reclassify</Button>
        </div>
      </div>

      <div class="viewer">
        <EvidenceViewer bind:value={tab}
          tabs={[{ value: 'text', label: 'Extracted text' }, { value: 'findings', label: 'Findings' }, { value: 'metadata', label: 'Metadata' }]}>
          <Tabs.Content value="text">
            {#if granted}
              <div class="pad"><CodeBlock code={d.extracted_text} /></div>
            {:else}
              <div class="gate">
                <p>Extracted text is served through the signed, journaled access step.</p>
                <Button variant="primary" size="sm" onclick={() => (accessOpen = true)}>Request access</Button>
              </div>
            {/if}
          </Tabs.Content>
          <Tabs.Content value="findings"><FindingsList classification={d.classification} /></Tabs.Content>
          <Tabs.Content value="metadata">
            <div class="meta">
              <div class="mrow"><span class="k">Document</span><span class="v">{d.document_id}</span></div>
              <div class="mrow"><span class="k">SHA-256</span><span class="v hash">{d.content_hash}</span></div>
              <div class="mrow"><span class="k">MIME</span><span class="v">{d.content_mime}</span></div>
              <div class="mrow"><span class="k">Kind</span><span class="v">{d.doc_kind}</span></div>
              <div class="mrow"><span class="k">Size</span><span class="v">{d.content_size.toLocaleString()} bytes</span></div>
              <div class="mrow"><span class="k">Uploaded</span><span class="v">{d.uploaded_at}</span></div>
              <div class="mrow"><span class="k">Ingested</span><span class="v">{d.ingested_at}</span></div>
            </div>
          </Tabs.Content>
        </EvidenceViewer>
      </div>
    </div>
  </div>
</main>

<AccessDialog bind:open={accessOpen} manifest={manifestOf} onconfirm={() => (granted = true)} />
<ReclassifyDialog bind:open={reclassOpen} subject={subjectOf} onconfirm={(r) => console.log('reclassify', r)} />

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(360px, 1.2fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 12px; min-height: 0; }

  .dhead { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .dtitle { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .dfile { font-family: var(--font-mono); font-size: var(--fs-14); letter-spacing: var(--tracking-data); color: var(--text); }

  .viewer { flex: 1; min-height: 0; display: flex; }
  .pad { padding: 12px; }
  .gate { padding: 24px; display: flex; flex-direction: column; gap: 12px; align-items: flex-start; }
  .gate p { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted); }

  .meta { padding: 4px 0; }
  .mrow { display: grid; grid-template-columns: 110px 1fr; gap: 12px; align-items: baseline; padding: 7px 12px; border-bottom: 1px solid var(--border); }
  .mrow:last-child { border-bottom: none; }
  .k { font-family: var(--font-sans); font-size: var(--fs-12); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .v { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .v.hash { word-break: break-all; color: var(--text-muted); }

  @media (max-width: 940px) { .body { grid-template-columns: 1fr; overflow: auto; } .viewer { min-height: 340px; } }
</style>
