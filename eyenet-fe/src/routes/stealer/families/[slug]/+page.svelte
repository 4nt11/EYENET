<script>
  // Family detail landing. For a given stealer-family slug, loads:
  //   - the family YAML metadata (name, aliases, references, signal set)
  //   - the per-family aggregate (victim count, top countries)
  //   - the victim card grid filtered to this family
  // All three independent; load in parallel.
  //
  // Phase 4 of the stealer-family classifier rollout; see
  // development/STEALER_FAMILY_CLASSIFIER_DESIGN.md.
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import SectionHeader from '$lib/components/SectionHeader.svelte';
  import StatTile from '$lib/components/StatTile.svelte';
  import Button from '$lib/components/Button.svelte';
  import { apiGet } from '$lib/api.js';
  import { getFamily } from '$lib/stealerFamiliesApi.svelte.js';

  const slug = $derived($page.params.slug);

  let family = $state(null);
  let familyErr = $state(null);
  let victims = $state([]);
  let victimsMeta = $state(null);
  let victimsPage = $state(1);
  let victimsLoading = $state(false);
  let victimsErr = $state(null);
  let agg = $state(null);

  const fmt = (n) => (n ?? 0).toLocaleString();
  const shortSha = (s) => (s ? s.slice(0, 8) : '');

  async function loadVictims(p = 1) {
    victimsLoading = true;
    try {
      const params = new URLSearchParams({ page: String(p), limit: '25', family: slug });
      const r = await apiGet(`/v1/stealer/artifacts?${params}`, { auth: true });
      victims = r.items ?? [];
      victimsMeta = r.page_meta ?? null;
      victimsPage = p;
    } catch (e) {
      victimsErr = e.message ?? String(e);
    } finally {
      victimsLoading = false;
    }
  }

  onMount(async () => {
    const tasks = [
      getFamily(slug).then((f) => (family = f)).catch((e) => (familyErr = e.message ?? String(e))),
      loadVictims(1),
    ];
    await Promise.all(tasks);
    // Derive aggregates from the first page of victims. For a real
    // aggregate we would add a dedicated endpoint; counting over the
    // page is honest enough for a landing header with a corpus of
    // a few hundred classified victims and avoids a second round trip.
    agg = {
      total: victimsMeta?.total ?? 0,
    };
  });

  const prev = () => loadVictims(Math.max(1, victimsPage - 1));
  const next = () => {
    const pc = victimsMeta?.page_count ?? 1;
    loadVictims(Math.min(pc, victimsPage + 1));
  };
  const openVictim = (sha, folder) => {
    goto(`/stealer/artifacts?open=${encodeURIComponent(sha + '/' + folder)}`);
  };
</script>

<main>
  <div class="head">
    <SectionHeader group="Stealer" slug={slug} title={family?.name || slug} />
    <div class="head-actions">
      <Button variant="ghost" size="sm" onclick={() => goto('/stealer/artifacts')}>All artifacts</Button>
      <Button variant="primary" size="sm" onclick={() => goto(`/tuning/stealer/families/${encodeURIComponent(slug)}`)}>
        Edit family
      </Button>
    </div>
  </div>

  {#if familyErr}
    <p class="note err">Family load failed: {familyErr}</p>
  {:else if !family}
    <p class="note">Loading family…</p>
  {:else}
    <section class="meta-row">
      <StatTile label="Classified victims" value={fmt(agg?.total ?? victimsMeta?.total ?? 0)} tone="accent" />
      <StatTile label="Kind" value={family.kind || 'stealer'} />
      <StatTile label="Status" value={family.status || '--'} />
      <StatTile label="First seen" value={family.first_seen_year || '--'} />
    </section>

    <section class="profile">
      <header><span class="n">01</span><span class="label">Profile</span></header>
      <div class="pad">
        {#if family.aliases?.length}
          <div class="row"><span class="k">Aliases</span><span class="v">{family.aliases.join(', ')}</span></div>
        {/if}
        {#if family.loaders?.length}
          <div class="row"><span class="k">Loaders</span><span class="v">{family.loaders.join(', ')}</span></div>
        {/if}
        {#if family.distribution_channels?.length}
          <div class="row"><span class="k">Distribution</span><span class="v">{family.distribution_channels.join(', ')}</span></div>
        {/if}
        {#if family.notes}
          <div class="row"><span class="k">Notes</span><span class="v">{family.notes}</span></div>
        {/if}
      </div>
    </section>

    {#if family.kind === 'stealer'}
      <section class="profile">
        <header><span class="n">02</span><span class="label">Signals</span><span class="hint">weights live in classifier.py</span></header>
        <div class="pad">
          {#if family.signature_files?.length}
            <div class="row"><span class="k">Files</span><span class="v mono">{family.signature_files.join(', ')}</span></div>
          {/if}
          {#if family.signature_paths?.length}
            <div class="row"><span class="k">Paths</span><span class="v mono">{family.signature_paths.join(', ')}</span></div>
          {/if}
          {#if family.signature_rule_ids?.length}
            <div class="row"><span class="k">Rule IDs</span><span class="v mono">{family.signature_rule_ids.join(', ')}</span></div>
          {/if}
          {#if family.build_tag_regex}
            <div class="row"><span class="k">build_tag_regex</span><span class="v mono accent">{family.build_tag_regex}</span></div>
          {/if}
          {#if family.antisignature_files?.length}
            <div class="row"><span class="k">Anti-files</span><span class="v mono muted">{family.antisignature_files.join(', ')}</span></div>
          {/if}
          {#if family.antisignature_rule_ids?.length}
            <div class="row"><span class="k">Anti-rules</span><span class="v mono muted">{family.antisignature_rule_ids.join(', ')}</span></div>
          {/if}
          {#if family.confidence_floor !== undefined && family.confidence_floor !== null}
            <div class="row"><span class="k">Confidence floor</span><span class="v mono">{family.confidence_floor}</span></div>
          {/if}
        </div>
      </section>
    {/if}

    {#if family.references?.length}
      <section class="profile">
        <header><span class="n">03</span><span class="label">References</span></header>
        <div class="pad refs">
          {#each family.references as r}
            <a href={r.url} target="_blank" rel="noopener">{r.title}</a>
          {/each}
        </div>
      </section>
    {/if}
  {/if}

  <section class="profile">
    <header>
      <span class="n">04</span>
      <span class="label">Attributed victims</span>
      {#if victimsMeta}
        <span class="hint">{fmt(victimsMeta.total)} total · page {victimsMeta.page}/{victimsMeta.page_count || 1}</span>
      {/if}
    </header>
    {#if victimsErr}
      <p class="note err">{victimsErr}</p>
    {:else if victimsLoading && victims.length === 0}
      <p class="note">Loading victims…</p>
    {:else if victims.length === 0}
      <p class="note">No victims attributed to this family.</p>
    {:else}
      <div class="grid">
        {#each victims as a (a.archive_sha256 + '/' + a.victim_folder)}
          <button class="card" onclick={() => openVictim(a.archive_sha256, a.victim_folder)}>
            <div class="row1">
              <span class="id mono">{shortSha(a.archive_sha256)}</span>
              <span class="cc mono">{a.country || '--'} · {a.traffic_affid || '--'}</span>
            </div>
            <div class="folder" title={a.victim_folder}>{a.victim_folder}</div>
            <div class="row3">
              <span>{fmt(a.creds_count)} creds</span>
              <span>{fmt(a.cookies_count)} cookies</span>
              {#if a.has_wallet}<span class="wallet">wallet</span>{/if}
            </div>
          </button>
        {/each}
      </div>
      <div class="pager">
        <Button variant="ghost" size="sm" disabled={victimsPage <= 1 || victimsLoading} onclick={prev}>Previous</Button>
        <Button variant="primary" size="sm" disabled={victimsLoading || !victimsMeta?.has_more} onclick={next}>Next page</Button>
      </div>
    {/if}
  </section>
</main>

<style>
  main { display: flex; flex-direction: column; gap: 16px; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .head-actions { display: flex; gap: 8px; }
  .meta-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
  @media (max-width: 900px) { .meta-row { grid-template-columns: repeat(2, 1fr); } }

  .profile { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  .profile > header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--panel-2); border-bottom: 1px solid var(--border); }
  .profile > header .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-label); }
  .profile > header .label { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .profile > header .hint { margin-left: auto; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); }
  .pad { padding: 10px 14px; display: flex; flex-direction: column; gap: 6px; }
  .row { display: grid; grid-template-columns: 160px 1fr; gap: 10px; font-size: var(--fs-12); }
  .row .k { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .row .v { color: var(--text); word-break: break-word; }
  .mono { font-family: var(--font-mono); letter-spacing: var(--tracking-data); }
  .accent { color: var(--accent-text); }
  .muted { color: var(--text-muted); }
  .refs { gap: 4px; }
  .refs a { color: var(--accent-text); text-decoration: none; }
  .refs a:hover { text-decoration: underline; }

  .note { padding: 10px 14px; font-size: var(--fs-12); color: var(--text-muted); }
  .note.err { color: var(--red-text); }

  .grid { padding: 10px 14px; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
  .card { text-align: left; cursor: pointer; display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); color: var(--text); }
  .card:hover { background: var(--panel-2); border-color: var(--accent); }
  .card .row1 { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
  .card .id { color: var(--accent-text); font-size: var(--fs-11); }
  .card .cc { color: var(--text-muted); font-size: var(--fs-11); }
  .card .folder { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .card .row3 { display: flex; gap: 10px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); }
  .card .row3 .wallet { color: var(--accent-text); }

  .pager { display: flex; justify-content: flex-end; gap: 8px; padding: 10px 14px; }
</style>
