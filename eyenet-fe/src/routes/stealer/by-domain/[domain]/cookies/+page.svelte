<script>
  // Cookies tab: leaked session cookies for this domain. Big data surface,
  // operator-usable because cookies are the auth tokens that bypass MFA
  // just like JWTs. Value is masked by default (purple bullets), reveal
  // + copy on click (red plaintext), expired cookies rendered muted +
  // struck-through so the operator triages the LIVE ones first.
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import Button from '$lib/components/Button.svelte';
  import { cookiesCtx, loadDomainCookies } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const shortSha = (s) => (s ? s.slice(0, 8) + s.slice(-4) : '');
  const relTime = (iso, isFuture = false) => {
    if (!iso) return '';
    const d = new Date(iso);
    const diffSec = (d.getTime() - Date.now()) / 1000;
    const abs = Math.abs(diffSec);
    const fmtD = (n, unit) => `${n}${unit}`;
    let s;
    if (abs < 60) s = fmtD(Math.round(abs), 's');
    else if (abs < 3600) s = fmtD(Math.round(abs / 60), 'm');
    else if (abs < 86400) s = fmtD(Math.round(abs / 3600), 'h');
    else if (abs < 86400 * 30) s = fmtD(Math.round(abs / 86400), 'd');
    else if (abs < 86400 * 365) s = fmtD(Math.round(abs / (86400 * 30)), 'mo');
    else s = fmtD(Math.round(abs / (86400 * 365)), 'y');
    return diffSec > 0 ? `in ${s}` : `${s} ago`;
  };
  const isExpired = (iso) => {
    if (!iso) return false; // session cookies render as no-exp, not expired
    return new Date(iso).getTime() < Date.now();
  };

  let domain = $derived($page.params.domain);

  onMount(() => loadDomainCookies(domain, { page: 1, live_only: cookiesCtx.live_only }));

  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainCookies(domain, { page: 1, live_only: cookiesCtx.live_only });
    }
  });

  const prev = () => cookiesCtx.page > 1 && loadDomainCookies(domain, { page: cookiesCtx.page - 1, live_only: cookiesCtx.live_only });
  const next = () => cookiesCtx.page < cookiesCtx.pages && loadDomainCookies(domain, { page: cookiesCtx.page + 1, live_only: cookiesCtx.live_only });
  const toggleLive = () => loadDomainCookies(domain, { page: 1, live_only: !cookiesCtx.live_only });

  // Mask cookie values by default (purple bullets); click to reveal + copy.
  // Same pattern as passwords.
  let revealed = $state(new Set());
  function toggleReveal(key, val) {
    const next = new Set(revealed);
    if (next.has(key)) next.delete(key);
    else { next.add(key); copy(val ?? ''); }
    revealed = next;
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); } catch { /* ignore */ }
  }
</script>

<section class="wrap">
  <div class="url-hint-row">
    <div class="url-hint">GET /v1/stealer/by-domain/{domain}/cookies?page={cookiesCtx.page}&amp;limit={cookiesCtx.limit}&amp;live_only={cookiesCtx.live_only}</div>
    <button type="button" class="live-toggle" class:on={cookiesCtx.live_only} onclick={toggleLive} disabled={cookiesCtx.loading}>
      <span class="dot"></span>
      Live only
    </button>
  </div>

  {#if cookiesCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if cookiesCtx.error}
    <div class="banner-error">{cookiesCtx.error}</div>
  {:else if cookiesCtx.loaded && cookiesCtx.items.length === 0}
    <div class="empty">
      {cookiesCtx.live_only
        ? `No live cookies for ${domain} in the corpus.`
        : `No cookies leaked to ${domain} in the corpus.`}
    </div>
  {:else}
    <div class="table-wrap">
      <table class="cookies">
        <thead>
          <tr>
            <th>Host</th>
            <th>Name</th>
            <th>Value</th>
            <th>Expires</th>
            <th>Flags</th>
            <th>Archive</th>
            <th>Victim</th>
          </tr>
        </thead>
        <tbody>
          {#each cookiesCtx.items as r, i (`${r.archive_sha256}:${r.victim_folder}:${r.host}:${r.name}:${i}`)}
            {@const rowKey = `${r.archive_sha256}:${r.victim_folder}:${r.host}:${r.name}:${i}`}
            {@const expired = isExpired(r.expires_at)}
            <tr class:expired>
              <td class="mono host" title={r.host}>{r.host}</td>
              <td class="mono name" title={r.name}>{r.name}</td>
              <td class="mono val">
                <button
                  type="button"
                  class="val-text"
                  class:revealed={revealed.has(rowKey)}
                  title={revealed.has(rowKey) ? (r.value ?? '') : 'Click to reveal + copy'}
                  onclick={() => toggleReveal(rowKey, r.value)}
                >
                  {revealed.has(rowKey) ? r.value : '•'.repeat(Math.min(14, r.value?.length ?? 0))}
                </button>
              </td>
              <td class="mono exp" class:exp-expired={expired} class:exp-live={!expired && r.expires_at}>
                {#if r.expires_at}
                  {relTime(r.expires_at)}
                {:else}
                  <span class="no-data">session</span>
                {/if}
              </td>
              <td class="flags">
                {#if r.http_only}<span class="flag flag-http">HttpOnly</span>{/if}
                {#if r.secure}<span class="flag flag-secure">Secure</span>{/if}
                {#if !r.http_only && !r.secure}<span class="no-data">none</span>{/if}
              </td>
              <td class="mono sha" title={r.archive_sha256}>{shortSha(r.archive_sha256)}</td>
              <td class="mono victim" title={r.victim_folder}>{r.victim_folder}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="pager">
      <div class="meta">
        Showing {fmt(cookiesCtx.items.length)} of {fmt(cookiesCtx.total)}
      </div>
      <div class="controls">
        <Button variant="ghost" onclick={prev} disabled={cookiesCtx.page <= 1 || cookiesCtx.loading}>Prev</Button>
        <span class="pageidx">{fmt(cookiesCtx.page)} / {fmt(cookiesCtx.pages)}</span>
        <Button variant="ghost" onclick={next} disabled={cookiesCtx.page >= cookiesCtx.pages || cookiesCtx.loading}>Next</Button>
      </div>
    </div>
  {/if}
</section>

<style>
  .wrap { display: flex; flex-direction: column; gap: 18px; }
  .url-hint-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .url-hint { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }

  .live-toggle {
    appearance: none; display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border: 1px solid var(--border); border-radius: 3px;
    background: transparent; color: var(--text-muted);
    font-family: var(--font-sans); font-size: var(--fs-12); cursor: pointer;
    transition: all 120ms ease;
  }
  .live-toggle:hover { color: var(--text-body); border-color: var(--border-strong); }
  .live-toggle.on { color: var(--red-text); border-color: var(--red); background: var(--red-fill); }
  .live-toggle .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-faint); }
  .live-toggle.on .dot { background: var(--red-text); box-shadow: 0 0 6px var(--red-text); }

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

  .table-wrap { border: 1px solid var(--border); border-radius: 4px; }

  table.cookies { width: 100%; border-collapse: collapse; }
  table.cookies th, table.cookies td {
    padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: left;
    font-family: var(--font-sans); font-size: var(--fs-12);
  }
  table.cookies thead th {
    background: var(--panel); color: var(--text-muted); font-weight: var(--fw-medium);
    text-transform: uppercase; font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    position: sticky; top: 0; z-index: 1;
  }
  table.cookies tr:last-child td { border-bottom: 0; }
  table.cookies tr:hover td { background: rgba(255,255,255,0.015); }

  /* Expired rows: muted + strike on the host/name so the operator skims
     for live ones first. Everything else stays readable. */
  table.cookies tr.expired td.host, table.cookies tr.expired td.name {
    text-decoration: line-through; color: var(--text-faint);
  }
  table.cookies tr.expired td { opacity: 0.75; }

  .mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  td.host { color: var(--text); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.name { color: var(--text-body); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.val { max-width: 260px; width: 260px; }
  td.exp { width: 110px; color: var(--text-muted); }
  td.exp.exp-live { color: var(--text-ok, #5bbf80); }
  td.exp.exp-expired { color: var(--red-text); }
  .flags { width: 160px; }
  td.sha { color: var(--text-muted); width: 130px; }
  td.victim { color: var(--text-muted); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .val-text {
    appearance: none; background: transparent; border: 0; padding: 2px 4px; border-radius: 2px;
    color: var(--accent-text); font-family: var(--font-mono); font-size: var(--fs-12); cursor: pointer;
    text-align: left; letter-spacing: 1px;
    /* Masked: hover tight to the bullets, inline-block so it sizes to content. */
    display: inline-block; max-width: 100%;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .val-text:hover { background: var(--accent-fill); }
  /* Revealed: let the long token wrap inside the cell so the ROW grows
     downward instead of bleeding into the neighbouring columns. */
  .val-text.revealed {
    color: var(--red-text); letter-spacing: 0;
    /* Revealed: inline-block sizes to content up to max-width; long tokens
       wrap inside this box, pushing the row taller downward. Short values
       keep a tight hover background. */
    display: inline-block; max-width: 100%;
    white-space: normal; overflow: visible; text-overflow: clip;
    word-break: break-all; line-height: 1.35;
  }
  .val-text.revealed:hover { background: var(--red-fill); }

  .flag {
    display: inline-flex; align-items: center;
    padding: 1px 7px; border-radius: 10px;
    font-family: var(--font-mono); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    text-transform: uppercase; letter-spacing: 0.06em; margin-right: 4px;
  }
  .flag-http { background: var(--accent-fill); color: var(--accent-text); border: 1px solid var(--accent-fill-strong); }
  .flag-secure { background: var(--panel-2); color: var(--text-body); border: 1px solid var(--border); }

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
