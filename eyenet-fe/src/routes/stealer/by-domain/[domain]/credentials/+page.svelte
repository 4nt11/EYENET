<script>
  // Credentials tab: paginated list of credential triples leaked to this
  // domain, read:stealer-gated. Each row is full operator evidence
  // (url + login + password + scheme + archive + victim + ingested_at).
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import Button from '$lib/components/Button.svelte';
  import { credentialsCtx, loadDomainCredentials } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const shortSha = (s) => (s ? s.slice(0, 8) + s.slice(-4) : '');
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

  onMount(() => loadDomainCredentials(domain, { page: 1 }));

  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainCredentials(domain, { page: 1 });
    }
  });

  const prev = () => credentialsCtx.page > 1 && loadDomainCredentials(domain, { page: credentialsCtx.page - 1 });
  const next = () => credentialsCtx.page < credentialsCtx.pages && loadDomainCredentials(domain, { page: credentialsCtx.page + 1 });

  // Mask passwords by default (purple bullets); click a cell to REVEAL it in
  // red plaintext + copy to clipboard in the same action. Click again to
  // re-mask. The audit-emit on the endpoint call already records that the
  // operator read these; masking is UX hygiene for over-the-shoulder viewing
  // and screen-shares, not a security barrier.
  let revealed = $state(new Set());
  function toggleReveal(key, pw) {
    const next = new Set(revealed);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
      copy(pw ?? '');
    }
    revealed = next;
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* ignore clipboard failures in non-secure contexts */
    }
  }
</script>

<section class="wrap">
  <div class="url-hint">GET /v1/stealer/by-domain/{domain}/credentials?page={credentialsCtx.page}&amp;limit={credentialsCtx.limit}</div>

  {#if credentialsCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if credentialsCtx.error}
    <div class="banner-error">{credentialsCtx.error}</div>
  {:else if credentialsCtx.loaded && credentialsCtx.items.length === 0}
    <div class="empty">
      No credentials leaked to <code>{domain}</code> in the corpus.
    </div>
  {:else}
    <div class="table-wrap">
      <table class="creds">
        <thead>
          <tr>
            <th>Host</th>
            <th>Login</th>
            <th>Password</th>
            <th>Scheme</th>
            <th>Archive</th>
            <th>Victim</th>
            <th>Ingested</th>
          </tr>
        </thead>
        <tbody>
          {#each credentialsCtx.items as r, i (`${r.archive_sha256}:${r.victim_folder}:${r.url}:${r.user}:${i}`)}
            {@const rowKey = `${r.archive_sha256}:${r.victim_folder}:${r.url}:${r.user}:${i}`}
            <tr>
              <td class="mono host"><span title={r.url}>{r.host}</span></td>
              <td class="mono user" title={r.user}>
                {#if r.user}
                  {r.user}
                {:else}
                  <span class="no-data">no user captured</span>
                {/if}
              </td>
              <td class="mono pw">
                <button
                  type="button"
                  class="pw-text"
                  class:revealed={revealed.has(rowKey)}
                  title={revealed.has(rowKey) ? (r.password ?? '') : 'Click to reveal + copy'}
                  onclick={() => toggleReveal(rowKey, r.password)}
                >
                  {revealed.has(rowKey) ? r.password : '•'.repeat(Math.min(14, r.password?.length ?? 0))}
                </button>
              </td>
              <td class="scheme">
                {#if r.scheme}
                  <span class="scheme-chip">{r.scheme}</span>
                {:else}
                  <span class="no-data">no scheme</span>
                {/if}
              </td>
              <td class="mono sha" title={r.archive_sha256}>{shortSha(r.archive_sha256)}</td>
              <td class="mono victim" title={r.victim_folder}>{r.victim_folder}</td>
              <td class="mono rel" title={r.ingested_at}>{relTime(r.ingested_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="pager">
      <div class="meta">
        Showing {fmt(credentialsCtx.items.length)} of {fmt(credentialsCtx.total)}
      </div>
      <div class="controls">
        <Button variant="ghost" onclick={prev} disabled={credentialsCtx.page <= 1 || credentialsCtx.loading}>
          Prev
        </Button>
        <span class="pageidx">
          {fmt(credentialsCtx.page)} / {fmt(credentialsCtx.pages)}
        </span>
        <Button variant="ghost" onclick={next} disabled={credentialsCtx.page >= credentialsCtx.pages || credentialsCtx.loading}>
          Next
        </Button>
      </div>
    </div>
  {/if}
</section>

<style>
  .wrap { display: flex; flex-direction: column; gap: 18px; }
  .url-hint {
    font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint);
  }

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
  /* overflow:hidden on .table-wrap would break position:sticky on thead,
     so we rely on cell styling instead to keep corners crisp. */

  table.creds { width: 100%; border-collapse: collapse; }
  table.creds th, table.creds td {
    padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: left;
    font-family: var(--font-sans); font-size: var(--fs-12);
  }
  table.creds thead th {
    background: var(--panel); color: var(--text-muted); font-weight: var(--fw-medium);
    text-transform: uppercase; font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    position: sticky; top: 0; z-index: 1;
  }
  table.creds tr:last-child td { border-bottom: 0; }
  table.creds tr:hover td { background: rgba(255,255,255,0.015); }

  .mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  td.host { color: var(--text); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.user { color: var(--text-body); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* No-data chip: EYENET metadata label, visually distinct from stealer-captured
     data. Hollow bordered pill in italic sans so it never gets mistaken for a
     real value the stealer actually grabbed. */
  .no-data {
    display: inline-flex; align-items: center;
    padding: 1px 8px; border: 1px dashed var(--border-strong); border-radius: 10px;
    font-family: var(--font-sans); font-size: var(--fs-11); font-style: italic;
    color: var(--text-faint); letter-spacing: 0; text-transform: none;
  }
  td.pw { max-width: 220px; width: 220px; }
  td.scheme { width: 80px; }

  /* Scheme chip: purple accent fill, mono uppercase. Visually signals
     this is a classified protocol tag, not raw text. */
  .scheme-chip {
    display: inline-flex; align-items: center;
    padding: 1px 8px; border: 1px solid var(--accent-fill-strong); border-radius: 10px;
    background: var(--accent-fill);
    color: var(--accent-text);
    font-family: var(--font-mono); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    text-transform: uppercase; letter-spacing: 0.08em;
  }
  td.sha { color: var(--text-muted); width: 110px; }
  td.victim { color: var(--text-muted); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.rel { color: var(--text-muted); width: 110px; }

  .pw-text {
    appearance: none; background: transparent; border: 0; padding: 2px 4px; border-radius: 2px;
    color: var(--accent-text); font-family: var(--font-mono); font-size: var(--fs-12); cursor: pointer;
    text-align: left; letter-spacing: 1px;
    display: inline-block; max-width: 100%;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .pw-text:hover { background: var(--accent-fill); }
  /* Revealed long tokens (JWTs, refresh tokens) wrap inside the cell so the
     row expands downward instead of bleeding into neighbouring columns. */
  .pw-text.revealed {
    color: var(--red-text); letter-spacing: 0;
    display: inline-block; max-width: 100%;
    white-space: normal; overflow: visible; text-overflow: clip;
    word-break: break-all; line-height: 1.35;
  }
  .pw-text.revealed:hover { background: var(--red-fill); }

  .pager {
    display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px;
  }
  .meta { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); }
  .controls { display: flex; align-items: center; gap: 10px; }
  .pageidx { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-muted); min-width: 64px; text-align: center; }
</style>
