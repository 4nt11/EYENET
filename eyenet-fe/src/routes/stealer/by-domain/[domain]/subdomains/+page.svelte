<script>
  // Subdomains tab: per-subdomain cred + cookie counts, ranked by cred volume.
  // Top row is the registrable itself; children are the individual subdomains
  // the stealer saw credentials/cookies against. No pagination (server-side
  // top-N limit). Visual weight scales with the ratio of this subdomain's
  // creds to the biggest.
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { subdomainsCtx, loadDomainSubdomains } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();

  let domain = $derived($page.params.domain);

  onMount(() => loadDomainSubdomains(domain));

  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainSubdomains(domain);
    }
  });

  // Add a bar-pct per row relative to the biggest cred count on screen.
  // Gives the operator a visual density hint without a chart.
  const rowsWithBars = $derived.by(() => {
    const items = subdomainsCtx.items ?? [];
    const max = Math.max(1, ...items.map((r) => r.credential_count));
    return items.map((r) => ({ ...r, bar_pct: Math.round((r.credential_count / max) * 100) }));
  });
</script>

<section class="wrap">
  <div class="url-hint">GET /v1/stealer/by-domain/{domain}/subdomains?limit={subdomainsCtx.limit}</div>

  {#if subdomainsCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if subdomainsCtx.error}
    <div class="banner-error">{subdomainsCtx.error}</div>
  {:else if subdomainsCtx.loaded && rowsWithBars.length === 0}
    <div class="empty">
      No subdomains seen for <code>{domain}</code> in the corpus.
    </div>
  {:else}
    <div class="table-wrap">
      <table class="subs">
        <thead>
          <tr>
            <th>Host</th>
            <th class="n">Credentials</th>
            <th class="n">Cookies</th>
            <th class="bar-col">Volume</th>
          </tr>
        </thead>
        <tbody>
          {#each rowsWithBars as r (r.host)}
            <tr>
              <td class="mono host">{r.host}</td>
              <td class="mono n cred">{fmt(r.credential_count)}</td>
              <td class="mono n cookie">{fmt(r.cookie_count)}</td>
              <td class="bar-col">
                <div class="bar-track">
                  <div class="bar-fill" style="width: {r.bar_pct}%"></div>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="meta">
      Showing {fmt(rowsWithBars.length)} of {fmt(subdomainsCtx.total)} distinct subdomains
    </div>
  {/if}
</section>

<style>
  .wrap { display: flex; flex-direction: column; gap: 18px; }
  .url-hint { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }

  .banner-warn, .banner-error {
    padding: 10px 14px; border-radius: 3px; font-family: var(--font-sans); font-size: var(--fs-13);
  }
  .banner-warn { border: 1px solid var(--warn-fill); background: var(--warn-fill); color: var(--warn-text); }
  .banner-error { border: 1px solid var(--red-fill); background: var(--red-fill); color: var(--red-text); }
  .banner-warn code { font-family: var(--font-mono); background: rgba(0,0,0,0.3); padding: 1px 4px; border-radius: 2px; }

  .empty {
    padding: 30px; text-align: center; color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13);
    border: 1px dashed var(--border); border-radius: 4px;
  }
  .empty code { font-family: var(--font-mono); color: var(--text-body); background: var(--panel); padding: 1px 4px; border-radius: 2px; }

  .table-wrap { border: 1px solid var(--border); border-radius: 4px; }

  table.subs { width: 100%; border-collapse: collapse; }
  table.subs th, table.subs td {
    padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: left;
    font-family: var(--font-sans); font-size: var(--fs-12);
  }
  table.subs thead th {
    background: var(--panel); color: var(--text-muted); font-weight: var(--fw-medium);
    text-transform: uppercase; font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    position: sticky; top: 0; z-index: 1;
  }
  table.subs th.n, table.subs td.n { text-align: right; }
  table.subs tr:last-child td { border-bottom: 0; }
  table.subs tr:hover td { background: rgba(255,255,255,0.015); }

  .mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  td.host { color: var(--text); }
  td.cred { color: var(--accent-text); width: 130px; font-weight: var(--fw-medium); }
  td.cookie { color: var(--text-body); width: 130px; }

  th.bar-col, td.bar-col { width: 30%; min-width: 180px; }
  .bar-track { height: 4px; background: rgba(255,255,255,0.04); border-radius: 2px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--accent-text); border-radius: 2px; transition: width 180ms ease; }

  .meta { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); padding-top: 4px; }
</style>
