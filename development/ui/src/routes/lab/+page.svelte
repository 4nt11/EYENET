<script>
  import { Tabs } from 'bits-ui';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import TierBadge from '$lib/components/TierBadge.svelte';
  import StubChip from '$lib/components/StubChip.svelte';
  import CodeBlock from '$lib/components/CodeBlock.svelte';
  import FindingsList from '$lib/components/FindingsList.svelte';
  import EvidenceViewer from '$lib/components/EvidenceViewer.svelte';
  import AccessDialog from '$lib/components/AccessDialog.svelte';
  import Button from '$lib/components/Button.svelte';

  let dlg = $state(false);

  const CLASSIFICATION = {
    tier: 'classified', fail_closed: false, consult_llm: false, ruleset_version: 'v4', pii_map_version: 'v2',
    provenance: [
      { stage: 'extraction', tier_floor: 'normal', fail_closed: false },
      { stage: 'regex', tier_floor: 'classified', fail_closed: false },
      { stage: 'presidio', tier_floor: 'restricted', fail_closed: false },
      { stage: 'metadata', tier_floor: 'normal', fail_closed: false }
    ],
    regex_matches: [{ rule: 'iban_marker', tier_floor: 'classified', start: 412, end: 444, lang: 'en', matched_text: 'GB●●●●●●●●●●●●' }],
    presidio_matches: [{ entity_type: 'CREDIT_CARD', tier_floor: 'restricted', start: 88, end: 104, language: 'en', score: 0.99, matched_text: '●●●●●●●●●●●●1234' }],
    review_flags: [{ kind: 'llm_higher_tier', detail: 'model judged content more sensitive', suggested_tier: 'classified', corroborated: false }],
    llm: { suggested_tier: 'classified', confidence: 'medium', model: 'ollama/llama', attempts: 1 }
  };

  const LEAK = JSON.stringify({ dump: 'supplier-portal', records: 2, rows: [{ user: 'a.reyes', hash: '$2b$12$…', role: 'admin' }, { user: 'svc', token: 'eyJ…' }] });
  const MANIFEST = { content_mime: 'image/png', content_size: 2048576, content_hash: 'a3f19e2c4b7d…b8d4', tier: 'normal' };
</script>

<main>
  <SectionHeader group="Dev" slug="lab" title="Component lab" />
  <div class="body">
    <section><h2>TierBadge</h2>
      <div class="row"><TierBadge tier="normal" /><TierBadge tier="restricted" /><TierBadge tier="classified" /><TierBadge tier="restricted" effective="classified" /></div>
    </section>

    <section><h2>StubChip</h2>
      <div class="row"><StubChip route="GET /v1/documents/{'{id}'}">No document read endpoint exists yet.</StubChip>
        <StubChip route="POST /v1/observations/{'{id}'}/reclassify">Reclassify handler is a 501 skeleton.</StubChip></div>
    </section>

    <section><h2>CodeBlock (auto-detect + JSON pretty-print)</h2>
      <CodeBlock code={LEAK} /></section>

    <section><h2>FindingsList</h2>
      <div class="framed"><FindingsList classification={CLASSIFICATION} /></div></section>

    <section><h2>EvidenceViewer (Bits UI tabs)</h2>
      <div class="viewer">
        <EvidenceViewer tabs={[{ value: 'text', label: 'Extracted text' }, { value: 'findings', label: 'Findings' }, { value: 'raw', label: 'Raw' }]}>
          <Tabs.Content value="text"><div class="pad"><CodeBlock code={LEAK} /></div></Tabs.Content>
          <Tabs.Content value="findings"><FindingsList classification={CLASSIFICATION} /></Tabs.Content>
          <Tabs.Content value="raw"><div class="pad muted">Raw byte view mounts here once access is wired.</div></Tabs.Content>
        </EvidenceViewer>
      </div>
    </section>

    <section><h2>AccessDialog (Bits UI dialog)</h2>
      <Button variant="primary" size="sm" onclick={() => (dlg = true)}>Request access</Button>
      <AccessDialog bind:open={dlg} manifest={MANIFEST} onconfirm={(a) => console.log('access', a)} />
    </section>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 24px; }
  section { display: flex; flex-direction: column; gap: 10px; }
  h2 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .framed { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); }
  .viewer { height: 360px; display: flex; }
  .pad { padding: 12px; }
  .muted { color: var(--text-faint); font-family: var(--font-sans); font-size: var(--fs-13); }
</style>
