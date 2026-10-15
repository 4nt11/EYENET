<script>
  import { onMount } from 'svelte';
  import DossierLayout from '$lib/components/DossierLayout.svelte';
  import DataTable from '$lib/components/DataTable.svelte';
  import Dropdown from '$lib/components/Dropdown.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import Badge from '$lib/components/Badge.svelte';
  import {
    artifactCtx,
    artifactFilters,
    artifactView,
    loadArtifacts,
    loadMoreArtifacts,
    applyFilters,
    loadArtifactMentions,
    loadMoreMentions
  } from '$lib/artifact.svelte.js';

  const SORT_OPTS = [
    { v: 'recent', l: 'Recent' },
    { v: 'mentions', l: 'Most mentioned' },
    { v: 'value', l: 'Value (A–Z)' },
    { v: 'first_seen', l: 'First seen' }
  ];
  const KIND_OPTS = [
    { v: '', l: 'All kinds' },
    { v: 'domain', l: 'domain' },
    { v: 'onion', l: 'onion' },
    { v: 'ipv4', l: 'ipv4' },
    { v: 'ipv6', l: 'ipv6' },
    { v: 'email', l: 'email' },
    { v: 'wallet_btc', l: 'wallet_btc' },
    { v: 'wallet_eth', l: 'wallet_eth' },
    { v: 'wallet_xmr', l: 'wallet_xmr' },
    { v: 'wallet_tron', l: 'wallet_tron' },
    { v: 'handle_other_platform', l: 'handle' },
    { v: 'session', l: 'session' },
    { v: 'tox', l: 'tox' },
    { v: 'pgp_key', l: 'pgp_key' }
  ];
  const RES_OPTS = [
    { v: '', l: 'Any resolution' },
    { v: 'RESOLVED', l: 'Resolved' },
    { v: 'UNRESOLVED', l: 'Unresolved' },
    { v: 'AMBIGUOUS', l: 'Ambiguous' },
    { v: 'NOT_APPLICABLE', l: 'N/A' }
  ];
  const RES_TONE = {
    RESOLVED: 'high',
    UNRESOLVED: 'neutral',
    AMBIGUOUS: 'warn',
    NOT_APPLICABLE: 'low'
  };

  const MENTION_COLUMNS = [
    { key: 'when', header: 'When', mono: true, width: '170px' },
    { key: 'who', header: 'Actor', mono: true, width: '190px' },
    { key: 'where', header: 'Group', mono: true },
    { key: 'charOffset', header: 'Offset', mono: true, width: '80px' }
  ];

  let selectedId = $state(null);
  let d = $derived(artifactCtx.list.find((a) => a.id === selectedId) ?? null);

  function onSelect(id) {
    selectedId = id;
    loadArtifactMentions(id);
  }

  onMount(() => loadArtifacts());
</script>

<DossierLayout listLabel="Artifacts"
  items={artifactCtx.list.map((x) => ({ id: x.id, primary: x.value, secondary: `${x.kind} · ${x.mentions}× · ${x.actors} actor${x.actors === 1 ? '' : 's'}` }))}
  selectedId={selectedId} {onSelect}
  onLoadMore={loadMoreArtifacts} hasMore={!!artifactCtx.nextCursor}
  selected={!!d}>

  {#snippet title()}
    {#if d}
      <span class="val">{d.value}</span>
      <span class="kind">{d.kind}</span>
    {:else}
      <span class="val muted">Artifacts</span>
    {/if}
  {/snippet}

  {#snippet filters()}
    <div class="fcount">{artifactCtx.total ?? artifactCtx.list.length} artifact{(artifactCtx.total ?? artifactCtx.list.length) === 1 ? '' : 's'}</div>
    <input class="search" type="text" placeholder="value contains…" spellcheck="false"
      bind:value={artifactFilters.q} oninput={applyFilters} />
    <Dropdown options={KIND_OPTS} bind:value={artifactFilters.kind} onchange={applyFilters} minWidth="150px" />
    <Dropdown options={RES_OPTS} bind:value={artifactFilters.resolutionState} onchange={applyFilters} minWidth="150px" />
    <Dropdown options={SORT_OPTS} bind:value={artifactFilters.sort} onchange={applyFilters} minWidth="150px" />
  {/snippet}

  {#snippet head()}
    <div class="badges">
      <Badge tone={RES_TONE[d.resolutionState] ?? 'neutral'}>{d.resolutionState.toLowerCase()}</Badge>
      {#if d.resolvedToSourceId}<a class="pbtn small" href={`/sources?id=${d.resolvedToSourceId}`}>resolved source</a>{/if}
    </div>
  {/snippet}

  {#snippet body()}
    <div class="tiles">
      <StatTile label="Mentions" value={d.mentions} />
      <StatTile label="Distinct actors" value={d.actors} />
      <StatTile label="Distinct groups" value={d.groups} />
      <StatTile label="First seen" value={d.firstMention.split(' ')[0]} sub={d.firstMention.split(' ')[1] ?? ''} />
      <StatTile label="Last seen" value={d.lastMention.split(' ')[0]} sub={d.lastMention.split(' ')[1] ?? ''} />
    </div>

    <Panel title="Mentioned by" class="grow">
      {#snippet action()}<span class="count">{artifactView.mentions.length} of {artifactView.mentionsTotal ?? artifactView.mentions.length}</span>{/snippet}
      {#if artifactView.loading}
        <div class="empty">Loading…</div>
      {:else if artifactView.error}
        <div class="empty err">Could not load mentions: {artifactView.error}</div>
      {:else if artifactView.mentions.length}
        <DataTable rowKey="messageId" columns={MENTION_COLUMNS} rows={artifactView.mentions} />
        {#if artifactView.mentionsCursor}
          <div class="more">
            <button class="tinybtn" disabled={artifactView.loadingMore} onclick={() => loadMoreMentions(d.id)}>
              {artifactView.loadingMore ? 'Loading…' : 'Load more'}
            </button>
          </div>
        {/if}
      {:else}
        <div class="empty">No recorded mentions.</div>
      {/if}
    </Panel>
  {/snippet}

  {#snippet empty()}
    <p class="pnote">
      {#if !artifactCtx.loaded}Loading…{:else if artifactCtx.error}Could not load artifacts: {artifactCtx.error}{:else}No artifacts match these filters.{/if}
    </p>
  {/snippet}
</DossierLayout>

<style>
  .val { font-family: var(--font-mono); font-size: var(--fs-18); font-weight: var(--fw-bold); letter-spacing: var(--tracking-data); color: var(--text); word-break: break-all; }
  .kind { font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .val.muted { color: var(--text-faint); }
  .fcount { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); white-space: nowrap; }
  .search { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12); padding: 6px 10px; min-width: 180px; }
  .search:focus { outline: none; border-color: var(--accent); }
  .badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0 0; }
  .pbtn.small { display: inline-flex; align-items: center; height: 22px; padding: 0 8px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-11); text-decoration: none; }
  .pbtn.small:hover { background: var(--panel-2); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .empty { padding: 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-faint); }
  .empty.err { color: var(--red-text); }
  .more { padding: 10px 12px; }
  .tinybtn { appearance: none; padding: 3px 8px; border: 1px solid var(--border-strong); border-radius: var(--radius); background: transparent; color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-11); cursor: pointer; }
  .tinybtn:hover:not(:disabled) { background: var(--panel-2); border-color: var(--accent); }
  .tinybtn:disabled { opacity: 0.5; cursor: default; }
  .pnote { margin: 0; padding: 16px 20px; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
</style>
