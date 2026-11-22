<script>
  // Domain View layout: hero summary + tab strip. Nested routes under here own
  // one tab each. The summary loads once on mount; tabs re-use summaryCtx.summary
  // for their badge counts without re-fetching.
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import StatTile from '$lib/components/StatTile.svelte';
  import { summaryCtx, loadDomainSummary } from '$lib/stealerByDomain.svelte.js';
  // Phosphor icons for the hero tiles and tab strip. Matches Design's mock.
  import Users from 'phosphor-svelte/lib/Users';
  import Package from 'phosphor-svelte/lib/Package';
  import Key from 'phosphor-svelte/lib/Key';
  import Cookie from 'phosphor-svelte/lib/Cookie';
  import TextT from 'phosphor-svelte/lib/TextT';
  import ClockCounterClockwise from 'phosphor-svelte/lib/ClockCounterClockwise';
  import BracketsCurly from 'phosphor-svelte/lib/BracketsCurly';
  import Flag from 'phosphor-svelte/lib/Flag';
  import TreeStructure from 'phosphor-svelte/lib/TreeStructure';
  import Shield from 'phosphor-svelte/lib/Shield';
  import Hash from 'phosphor-svelte/lib/Hash';
  import ArrowLeft from 'phosphor-svelte/lib/ArrowLeft';
  import ArrowsInLineHorizontal from 'phosphor-svelte/lib/ArrowsInLineHorizontal';

  let { children } = $props();

  const fmt = (n) => (n ?? 0).toLocaleString();
  const liveTone = (live) => (live > 0 ? 'critical' : 'default');

  let domain = $derived($page.params.domain);

  const TABS = [
    { slug: 'credentials', label: 'Credentials', countKey: 'credential_count', icon: Key },
    { slug: 'victims', label: 'Victims', countKey: 'victim_count', icon: Users },
    { slug: 'subdomains', label: 'Subdomains', countKey: null, icon: TreeStructure },
    { slug: 'cookies', label: 'Cookies', countKey: 'all_cookie_count', icon: Cookie },
    { slug: 'autofills', label: 'Autofills', countKey: 'autofill_count', icon: TextT },
    { slug: 'history', label: 'History', countKey: 'history_count', icon: ClockCounterClockwise },
    { slug: 'indicators', label: 'Indicators', countKey: 'indicator_hit_count', icon: Flag },
    { slug: 'localstorage', label: 'localStorage', countKey: 'localstorage_jwt_count', icon: BracketsCurly },
    { slug: 'antiviruses', label: 'Antiviruses', countKey: null, icon: Shield },
    { slug: 'samples', label: 'Samples', countKey: null, icon: Hash },
  ];

  const tabHref = (slug) => `/stealer/by-domain/${encodeURIComponent(domain)}/${slug}`;
  const isActive = (slug, path) => path?.endsWith(`/${slug}`) || (slug === 'credentials' && path?.endsWith(`/${encodeURIComponent(domain)}`));


  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainSummary(domain);
    }
  });

  const s = $derived(summaryCtx.summary);
  const normalised = $derived(
    summaryCtx.raw && s?.canonical_domain && summaryCtx.raw !== s.canonical_domain
  );
  const live = $derived(s?.live_cookie_count ?? 0);
  const allCookies = $derived(s?.all_cookie_count ?? 0);
  // Rolling indicator: visible while we're fetching the summary OR when the
  // backend reports a reindex mid-flight. Both conditions mean the number on
  // screen may shift under the operator's eye.
  const live_feed = $derived(summaryCtx.loading || !!s?.reindex_in_flight);
</script>

<main>
  <header class="head">
   <div class="head-inner">
    <div class="topbar">
      <a href="/stealer/by-domain" class="back">
        <ArrowLeft size={12} weight="regular" />
        <span>Search</span>
      </a>
      <span class="slug-tag">01 &middot; DOMAIN VIEW</span>
    </div>

    <div class="crumb">
      <span class="group">/domains/</span>
      <span class="val">{s?.canonical_domain ?? domain}</span>
    </div>

    {#if summaryCtx.denied}
      <div class="banner-warn">
        You lack the <code>read:stealer</code> clearance. Request a grant from
        an operator with <code>admin:stealer</code> rights.
      </div>
    {:else if summaryCtx.error}
      <div class="banner-error">{summaryCtx.error}</div>
    {:else}
      <section class="hero-card">
        <div class="hero-head">
          <div class="hero-head-left">
            <span class="hero-label">Domain</span>
            <h1 class="hero-title">{s?.canonical_domain ?? domain}</h1>
            {#if normalised}
              <div class="banner-normalise">
                <ArrowsInLineHorizontal size={12} weight="regular" />
                Query normalised from
                <code>{summaryCtx.raw}</code>
                to
                <code>{s.canonical_domain}</code>
              </div>
            {/if}
          </div>
          <div class="hero-head-right">
            {#if (s?.indicator_hit_count ?? 0) > 0}
              <span class="ind-badge">
                <span class="dot"></span>
                {fmt(s.indicator_hit_count)} INDICATOR HIT{s.indicator_hit_count === 1 ? '' : 'S'}
              </span>
            {/if}
            {#if s?.first_seen_at || s?.last_seen_at}
              <div class="seen">
                {#if s?.first_seen_at}
                  <div class="seen-row"><span class="seen-label">FIRST</span><code>{s.first_seen_at.replace('T', ' ').replace(/\.\d+Z?$/, 'Z')}</code></div>
                {/if}
                {#if s?.last_seen_at}
                  <div class="seen-row"><span class="seen-label">LAST</span><code>{s.last_seen_at.replace('T', ' ').replace(/\.\d+Z?$/, 'Z')}</code></div>
                {/if}
              </div>
            {/if}
          </div>
        </div>

        {#if s?.reindex_in_flight}
          <div class="banner-reindex">
            Reindex in progress &middot; counts may shift as the corpus reprocesses.
          </div>
        {/if}

        <section class="tiles">
          <StatTile label="Victims" value={fmt(s?.victim_count)} loader={live_feed} icon={Users} />
          <StatTile label="Archives" value={fmt(s?.archive_count)} loader={live_feed} icon={Package} />
          <StatTile label="Credentials" value={fmt(s?.credential_count)} tone="accent" loader={live_feed} icon={Key} />
          <StatTile
            label="Live cookies"
            value={fmt(live)}
            sub={`/ ${fmt(allCookies)}`}
            tone={liveTone(live)}
            loader={live_feed}
            icon={Cookie}
          />
          <StatTile label="Autofills" value={fmt(s?.autofill_count)} loader={live_feed} icon={TextT} />
          <StatTile label="History" value={fmt(s?.history_count)} loader={live_feed} icon={ClockCounterClockwise} />
          <StatTile label="JWT in localStorage" value={fmt(s?.localstorage_jwt_count)} tone={liveTone(s?.localstorage_jwt_count)} loader={live_feed} icon={BracketsCurly} />
          <StatTile label="Indicator hits" value={fmt(s?.indicator_hit_count)} tone={s?.indicator_hit_count > 0 ? 'critical' : 'default'} loader={live_feed} icon={Flag} />
        </section>
      </section>
    {/if}

    <nav class="tabs">
      {#each TABS as t (t.slug)}
        {@const count = t.countKey ? s?.[t.countKey] : null}
        {@const TabIcon = t.icon}
        <a href={tabHref(t.slug)} class="tab" class:active={isActive(t.slug, $page.url.pathname)}>
          <TabIcon size={13} weight="regular" />
          <span>{t.label}</span>
          {#if count != null}<span class="count">{fmt(count)}</span>{/if}
        </a>
      {/each}
    </nav>
   </div>
  </header>

  <section class="body">
    <div class="body-inner">
      {@render children()}
    </div>
  </section>
</main>

<style>
  /* Single scrolling surface: main IS the scroll container. The hero,
     tabs, and tab body are one continuous page; the browser's scrollbar
     carries the whole thing. Table body rows become the only
     "obviously scrolling" visual via a sticky table header that stays
     glued at the top once the hero scrolls out of view. */
  main { flex: 1; min-width: 0; overflow: auto; background: var(--black); }
  /* Mock spec: 24px top/bottom padding, 20px gap between all stacked blocks,
     1440 max-width. Pure gap-based vertical rhythm, no margins. */
  .head-inner, .body-inner { max-width: 1440px; margin: 0 auto; padding: 24px 20px 0; box-sizing: border-box; display: flex; flex-direction: column; gap: 20px; }
  .body-inner { padding: 20px; }

  .topbar { display: flex; align-items: center; gap: 12px; }
  .back {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 8px; border: 1px solid var(--border); border-radius: 3px;
    color: var(--text-muted); text-decoration: none;
    font-family: var(--font-mono); font-size: var(--fs-11);
  }
  .back:hover { color: var(--accent-text); border-color: var(--accent); }
  .slug-tag {
    font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint);
    letter-spacing: var(--tracking-data); text-transform: uppercase;
  }

  .crumb { display: flex; align-items: baseline; gap: 2px; font-family: var(--font-mono); font-size: var(--fs-11); }
  .group { color: var(--text-faint); }
  .val { color: var(--text); }

  .hero-card {
    border: 1px solid var(--border); border-radius: 4px;
    background: var(--panel);
    padding: 18px 20px;
    display: flex; flex-direction: column; gap: 16px;
  }
  .hero-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; }
  .hero-head-left { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .hero-head-right { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }

  .hero-label { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: 0.1em; text-transform: uppercase; font-weight: var(--fw-semibold); }
  .hero-title { margin: 0; font-family: var(--font-mono); font-size: 26px; letter-spacing: -0.02em; font-weight: var(--fw-regular); color: var(--text); word-break: break-all; }

  .ind-badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border: 1px solid var(--red-fill-strong); border-radius: 3px;
    background: var(--red-fill); color: var(--red-text);
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label);
  }
  .ind-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--red-text); }

  .seen { display: flex; flex-direction: row; gap: 14px; align-items: baseline; flex-wrap: wrap; justify-content: flex-end; }
  .seen-row { display: inline-flex; align-items: baseline; gap: 8px; }
  .seen-label { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: 0.1em; text-transform: uppercase; font-weight: var(--fw-semibold); }
  .seen-row code { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); }

  .banner-normalise {
    display: flex; align-items: center; gap: 6px;
    font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted);
  }
  .banner-normalise code { font-family: var(--font-mono); color: var(--text-body); background: var(--panel); padding: 1px 6px; border-radius: 3px; }
  .banner-normalise .pi { font-family: var(--font-mono); font-size: 11px; color: var(--text-faint); }

  .banner-reindex {
    padding: 8px 12px; border: 1px solid var(--warn-fill); background: var(--warn-fill);
    color: var(--warn-text); font-family: var(--font-sans); font-size: var(--fs-13);
    border-radius: 3px; margin: 8px 0;
  }

  .banner-warn, .banner-error {
    padding: 10px 14px; border-radius: 3px; font-family: var(--font-sans); font-size: var(--fs-13);
    margin: 8px 0;
  }
  .banner-warn { border: 1px solid var(--warn-fill); background: var(--warn-fill); color: var(--warn-text); }
  .banner-error { border: 1px solid var(--red-fill); background: var(--red-fill); color: var(--red-text); }
  .banner-warn code { font-family: var(--font-mono); background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 2px; }

  /* Mock's shared-hairline grid: tiles sit on a bg-border backdrop with 1px
     gaps, radius clips the corners. Looks tight and clean without tile-level
     borders. StatTile's own border/background is overridden inside this
     grid so the surface shows through the 1px gaps. */
  .tiles {
    display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px;
    border: 1px solid var(--border); border-radius: 4px;
    background: var(--border); overflow: hidden;
  }
  .tiles :global(.tile) {
    border: 0; border-radius: 0; background: var(--surface);
    padding: 12px 18px; gap: 10px;
  }
  @media (max-width: 1100px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

  .tabs { display: flex; gap: 2px; margin-top: 16px; overflow-x: auto; }
  .tab {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 14px 10px;
    font-family: var(--font-sans); font-size: var(--fs-13);
    color: var(--text-muted); text-decoration: none;
    border-bottom: 2px solid transparent; white-space: nowrap;
    transition: color 120ms ease, border-color 120ms ease;
  }
  .tab :global(svg) { flex: 0 0 auto; color: inherit; opacity: 0.8; }
  .tab:hover { color: var(--text-body); }
  .tab.active { color: var(--accent-text); border-bottom-color: var(--accent-text); }
  .tab.active :global(svg) { opacity: 1; }
  .tab .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }

  .body { min-height: 0; }
</style>
