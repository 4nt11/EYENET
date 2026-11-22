<script>
  // Victims tab: machines that leaked to this domain. The forensic timeline
  // column (SAMPLE / loader_md5) is why operators love this tab - "block
  // this MD5 in EDR" is one copy away.
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import Button from '$lib/components/Button.svelte';
  import Copy from 'phosphor-svelte/lib/Copy';
  import { victimsCtx, loadDomainVictims } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const shortSha = (s) => (s ? s.slice(0, 8) + s.slice(-4) : '');
  const shortMd5 = (s) => (s ? s.slice(0, 10) : '');
  const relTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    const diffSec = (Date.now() - d.getTime()) / 1000;
    if (!Number.isFinite(diffSec)) return iso;
    if (diffSec < 60) return `${Math.round(diffSec)}s ago`;
    if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
    if (diffSec < 86400 * 30) return `${Math.round(diffSec / 86400)}d ago`;
    if (diffSec < 86400 * 365) return `${Math.round(diffSec / (86400 * 30))}mo ago`;
    return `${Math.round(diffSec / (86400 * 365))}y ago`;
  };

  let domain = $derived($page.params.domain);


  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainVictims(domain, { page: 1 });
    }
  });

  const prev = () => victimsCtx.page > 1 && loadDomainVictims(domain, { page: victimsCtx.page - 1 });
  const next = () => victimsCtx.page < victimsCtx.pages && loadDomainVictims(domain, { page: victimsCtx.page + 1 });

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); } catch { /* ignore */ }
  }
</script>

<section class="wrap">
  <div class="url-hint">GET /v1/stealer/by-domain/{domain}/victims?page={victimsCtx.page}&amp;limit={victimsCtx.limit}</div>

  {#if victimsCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if victimsCtx.error}
    <div class="banner-error">{victimsCtx.error}</div>
  {:else if victimsCtx.loaded && victimsCtx.items.length === 0}
    <div class="empty">
      No victims leaked to <code>{domain}</code> in the corpus.
    </div>
  {:else}
    <div class="table-wrap">
      <table class="victims">
        <thead>
          <tr>
            <th>Archive</th>
            <th>Victim</th>
            <th>Country</th>
            <th>Build</th>
            <th>Sample</th>
            <th class="n">Creds</th>
            <th class="n">Cookies</th>
            <th>First seen</th>
          </tr>
        </thead>
        <tbody>
          {#each victimsCtx.items as r, i (`${r.archive_sha256}:${r.victim_folder}:${i}`)}
            <tr>
              <td class="mono sha" title={r.archive_sha256}>{shortSha(r.archive_sha256)}</td>
              <td class="mono victim" title={r.victim_folder}>{r.victim_folder}</td>
              <td class="mono country">
                {#if r.country}
                  <span class="country-chip">{r.country}</span>
                {:else}
                  <span class="no-data">no country</span>
                {/if}
              </td>
              <td class="mono build" title={r.build_version}>
                {#if r.build_version}{r.build_version}{:else}<span class="no-data">no build</span>{/if}
              </td>
              <td class="sample">
                {#if r.loader_md5}
                  <button type="button" class="md5" title="Copy full MD5 ({r.loader_md5})" onclick={() => copy(r.loader_md5)}>
                    <span class="md5-short">{shortMd5(r.loader_md5)}</span>
                    <Copy size={11} weight="regular" />
                  </button>
                {:else}
                  <span class="no-data">no sample metadata</span>
                {/if}
              </td>
              <td class="mono n cred">{fmt(r.credential_count)}</td>
              <td class="mono n cookie">{fmt(r.cookie_count)}</td>
              <td class="mono rel" title={r.first_seen_at}>{relTime(r.first_seen_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="pager">
      <div class="meta">
        Showing {fmt(victimsCtx.items.length)} of {fmt(victimsCtx.total)}
      </div>
      <div class="controls">
        <Button variant="ghost" onclick={prev} disabled={victimsCtx.page <= 1 || victimsCtx.loading}>Prev</Button>
        <span class="pageidx">{fmt(victimsCtx.page)} / {fmt(victimsCtx.pages)}</span>
        <Button variant="ghost" onclick={next} disabled={victimsCtx.page >= victimsCtx.pages || victimsCtx.loading}>Next</Button>
      </div>
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

  table.victims { width: 100%; border-collapse: collapse; }
  table.victims th, table.victims td {
    padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: left;
    font-family: var(--font-sans); font-size: var(--fs-12);
  }
  table.victims thead th {
    background: var(--panel); color: var(--text-muted); font-weight: var(--fw-medium);
    text-transform: uppercase; font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    position: sticky; top: 0; z-index: 1;
  }
  table.victims th.n, table.victims td.n { text-align: right; }
  table.victims tr:last-child td { border-bottom: 0; }
  table.victims tr:hover td { background: rgba(255,255,255,0.015); }

  .mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  td.sha { color: var(--text-muted); width: 130px; }
  td.victim { color: var(--text); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.country { width: 80px; }
  td.build { color: var(--text-body); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.sample { width: 170px; }
  td.cred { color: var(--accent-text); width: 90px; font-weight: var(--fw-medium); }
  td.cookie { color: var(--text-body); width: 90px; }
  td.rel { color: var(--text-muted); width: 110px; }

  /* Country chip: hollow mono uppercase pill. ISO 3166-1 alpha-2 reads at a glance. */
  .country-chip {
    display: inline-flex; align-items: center;
    padding: 1px 7px; border: 1px solid var(--border); border-radius: 10px;
    background: transparent; color: var(--text-body);
    font-family: var(--font-mono); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    text-transform: uppercase; letter-spacing: 0.06em;
  }

  /* Sample MD5: click-to-copy, muted mono with a trailing Copy glyph. Hover
     makes the MD5 text purple to suggest the copy action. */
  .md5 {
    appearance: none; background: transparent; border: 1px solid transparent;
    padding: 2px 6px; border-radius: 3px; cursor: pointer;
    display: inline-flex; align-items: center; gap: 6px;
    color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12);
  }
  .md5:hover { border-color: var(--accent-fill-strong); background: var(--accent-fill); color: var(--accent-text); }
  .md5 :global(svg) { color: var(--text-faint); }
  .md5:hover :global(svg) { color: var(--accent-text); }
  .md5-short { letter-spacing: 0; }

  /* No-data chip shared with credentials: EYENET metadata, not stealer data. */
  .no-data {
    display: inline-flex; align-items: center;
    padding: 1px 8px; border: 1px dashed var(--border-strong); border-radius: 10px;
    font-family: var(--font-sans); font-size: var(--fs-11); font-style: italic;
    color: var(--text-faint);
  }

  .pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px; }
  .meta { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); }
  .controls { display: flex; align-items: center; gap: 10px; }
  .pageidx { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-muted); min-width: 64px; text-align: center; }
</style>
