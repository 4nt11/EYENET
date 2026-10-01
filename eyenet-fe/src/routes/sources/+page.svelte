<script>
  import { onMount } from 'svelte';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import EvidencePanel from '$lib/components/EvidencePanel.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Button from '$lib/components/Button.svelte';
  import { sourceCtx, sourceView, sourceCreate, sourceDelete, loadSources, loadSourceDetail, createSource, deleteSource } from '$lib/source.svelte.js';

  const KINDS = ['telegram', 'matrix', 'irc', 'discord', 'forum', 'rss', 'xmpp'];
  let newKind = $state('telegram');
  let newName = $state('');
  let newNotes = $state('');
  const canCreate = $derived(newName.trim().length >= 1 && !sourceCreate.submitting);

  async function submitSource(e) {
    e.preventDefault();
    if (!canCreate) return;
    const id = await createSource({ kind: newKind, display_name: newName.trim(), notes: newNotes.trim() });
    if (id) {
      newName = '';
      newNotes = '';
      selectedId = id;
    }
  }

  // Columns are the fields /v1/sources actually returns. No `state` badge and
  // no `lastIngest` — the API has no backing field for either (see PR notes).
  const SOURCE_COLUMNS = [
    { key: 'id', header: 'Source', mono: true, width: '260px' },
    { key: 'platform', header: 'Platform', mono: true, width: '90px' },
    { key: 'name', header: 'Name', mono: true },
    { key: 'domainCount', header: 'Domains', mono: true, align: 'right', width: '90px' },
    { key: 'created', header: 'Created', mono: true, align: 'right', width: '190px' }
  ];

  let selectedId = $state(null);
  let sel = $derived(sourceCtx.list.find((s) => s.id === selectedId) ?? sourceCtx.list[0] ?? null);

  let detail = $derived(
    sel
      ? [
          { label: 'Source', value: sel.id },
          { label: 'Platform', value: sel.platform, tone: 'accent' },
          { label: 'Name', value: sel.name },
          { label: 'Canonical URL', value: sel.canonicalUrl ?? '—' },
          { label: 'Created', value: sel.created },
          { label: 'Resolved artifacts', value: String(sourceView.resolvedCount) }
        ]
      : []
  );

  // Fetch the selected source's detail (active domains) whenever selection moves.
  $effect(() => {
    if (sel) loadSourceDetail(sel.id);
  });

  async function removeSource() {
    if (!sel) return;
    if (!confirm(`Delete source "${sel.name}"? Only works if nothing references it.`)) return;
    const gone = await deleteSource(sel.id);
    if (gone) selectedId = null; // fall back to the first remaining source
  }

  onMount(loadSources); // populate the list from /v1/sources
</script>

<main>
  <SectionHeader group="Discovery" slug="sources" title="Sources" />

  <div class="body">
    <div class="table-col">
      <form class="newsrc" onsubmit={submitSource}>
        <select class="fin" bind:value={newKind} aria-label="Platform">
          {#each KINDS as k}<option value={k}>{k}</option>{/each}
        </select>
        <input class="fin grow" type="text" bind:value={newName} placeholder="New source display name" />
        <input class="fin grow" type="text" bind:value={newNotes} placeholder="Notes (optional)" />
        <Button variant="primary" size="sm" type="submit" disabled={!canCreate}>Add source</Button>
      </form>
      {#if sourceCreate.error}<p class="pnote err">Failed: {sourceCreate.error}</p>{/if}
      {#if sourceCreate.ok}<p class="pnote ok">{sourceCreate.ok}</p>{/if}
      {#if sourceCtx.list.length}
        <DataTable rowKey="id" columns={SOURCE_COLUMNS} rows={sourceCtx.list}
          selectedId={sel?.id} onRowClick={(r) => (selectedId = r.id)} />
      {:else}
        <p class="pnote">
          {#if !sourceCtx.loaded}Loading...{:else if sourceCtx.error}Could not load sources: {sourceCtx.error}{:else}No sources configured.{/if}
        </p>
      {/if}
    </div>

    <div class="detail-col">
      <EvidencePanel title={`Source · ${sel?.id ?? '—'}`} items={detail} labelWidth={120} />

      {#if sel}
        <div class="danger">
          <Button variant="destructive" size="sm" disabled={sourceDelete.submitting} onclick={removeSource}>
            {sourceDelete.submitting ? 'Deleting...' : 'Delete source'}
          </Button>
          {#if sourceDelete.error}<p class="pnote err">{sourceDelete.error}</p>{/if}
          {#if sourceDelete.ok}<p class="pnote ok">{sourceDelete.ok}</p>{/if}
        </div>
      {/if}

      <Panel title={`Source domains · ${sourceView.domains.length}`} class="domains">
        {#if sourceView.domains.length}
          {#each sourceView.domains as d}
            <div class="drow"><span class="dname">{d}</span></div>
          {/each}
        {:else}
          <div class="empty">
            {#if sourceView.loading}Loading...{:else if sourceView.error}Could not load domains: {sourceView.error}{:else}No active domains for this source.{/if}
          </div>
        {/if}
      </Panel>
    </div>
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, 1fr); gap: 16px; padding: 16px 20px; overflow: hidden; }
  .table-col { min-height: 0; overflow: auto; }
  .detail-col { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow: auto; }

  :global(.panel.domains) { flex: 0 0 auto; max-height: 200px; }
  .drow { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 12px; border-bottom: 1px solid var(--border); }
  .drow:last-child { border-bottom: none; }
  .dname { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-body); }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .pnote { margin: 0; padding: 12px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .pnote.err { color: var(--red-text); }
  .pnote.ok { color: var(--accent); }
  .danger { display: flex; flex-direction: column; gap: 6px; padding: 4px 0; }
  .newsrc { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 9px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .fin.grow { flex: 1; min-width: 0; }

  @media (max-width: 900px) { .body { grid-template-columns: 1fr; overflow: auto; } }
</style>
