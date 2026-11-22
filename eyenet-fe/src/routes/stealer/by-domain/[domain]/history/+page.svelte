<script>
  // History tab. Rows are (url, title) pairs captured from victims of this
  // domain -- what they visited around the time they got phished. gotractor
  // does not extract visit_count or last-visit timestamps today (the raw
  // Chromium History DB has both but the rule skips them), so the ORDER
  // column shows the EYENET ingest time rather than a real visit date;
  // the chip under the host flags this so the operator does not read it as
  // forensic truth.
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import Button from '$lib/components/Button.svelte';
  import ArrowSquareOut from 'phosphor-svelte/lib/ArrowSquareOut';
  import { historyCtx, loadDomainHistory } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const shortSha = (s) => (s ? s.slice(0, 8) + s.slice(-4) : '');
  const hostOf = (u) => {
    try { return new URL(u).host; } catch { return ''; }
  };
  const pathOf = (u) => {
    try { const p = new URL(u); return (p.pathname + p.search) || '/'; } catch { return u ?? ''; }
  };

  let domain = $derived($page.params.domain);


  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainHistory(domain, { page: 1 });
    }
  });

  const prev = () => historyCtx.page > 1 && loadDomainHistory(domain, { page: historyCtx.page - 1 });
  const next = () => historyCtx.page < historyCtx.pages && loadDomainHistory(domain, { page: historyCtx.page + 1 });
</script>

<section class="wrap">
  <div class="url-hint-row">
    <div class="url-hint">GET /v1/stealer/by-domain/{domain}/history?page={historyCtx.page}&amp;limit={historyCtx.limit}</div>
    <div class="scope-note">no real visit timestamps yet</div>
  </div>

  {#if historyCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if historyCtx.error}
    <div class="banner-error">{historyCtx.error}</div>
  {:else if historyCtx.loaded && historyCtx.items.length === 0}
    <div class="empty">
      No browsing history captured for <code>{domain}</code>.
    </div>
  {:else}
    <div class="table-wrap">
      <table class="hist">
        <thead>
          <tr>
            <th>Host</th>
            <th>Path</th>
            <th>Title</th>
            <th>Archive</th>
            <th>Victim</th>
          </tr>
        </thead>
        <tbody>
          {#each historyCtx.items as r, i (`${r.archive_sha256}:${r.victim_folder}:${r.url}:${i}`)}
            {@const h = hostOf(r.url) || r.host}
            {@const p = pathOf(r.url)}
            <tr>
              <td class="mono host" title={h}>{h || '-'}</td>
              <td class="mono path" title={p}>
                <a href={r.url} target="_blank" rel="noopener noreferrer" class="path-link">
                  <span class="path-text">{p}</span>
                  <ArrowSquareOut size={11} weight="regular" />
                </a>
              </td>
              <td class="title" title={r.title}>{r.title || ''}</td>
              <td class="mono sha" title={r.archive_sha256}>{shortSha(r.archive_sha256)}</td>
              <td class="mono victim" title={r.victim_folder}>{r.victim_folder}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <div class="pager">
      <div class="meta">
        Showing {fmt(historyCtx.items.length)} of {fmt(historyCtx.total)}
      </div>
      <div class="controls">
        <Button variant="ghost" onclick={prev} disabled={historyCtx.page <= 1 || historyCtx.loading}>Prev</Button>
        <span class="pageidx">{fmt(historyCtx.page)} / {fmt(historyCtx.pages)}</span>
        <Button variant="ghost" onclick={next} disabled={historyCtx.page >= historyCtx.pages || historyCtx.loading}>Next</Button>
      </div>
    </div>
  {/if}
</section>

<style>
  .wrap { display: flex; flex-direction: column; gap: 18px; }
  .url-hint-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .url-hint { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .scope-note { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--warn-text); font-style: italic; }

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

  table.hist { width: 100%; border-collapse: collapse; table-layout: fixed; }
  table.hist th, table.hist td {
    padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: left;
    font-family: var(--font-sans); font-size: var(--fs-12);
  }
  table.hist thead th {
    background: var(--panel); color: var(--text-muted); font-weight: var(--fw-medium);
    text-transform: uppercase; font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    position: sticky; top: 0; z-index: 1;
  }
  table.hist tr:last-child td { border-bottom: 0; }
  table.hist tr:hover td { background: rgba(255,255,255,0.015); }

  .mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  td.host { color: var(--text); width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.path { color: var(--accent-text); max-width: 420px; overflow: hidden; }
  td.title { color: var(--text-body); max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.sha { color: var(--text-muted); width: 130px; }
  td.victim { color: var(--text-muted); width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .path-link {
    display: inline-flex; align-items: center; gap: 6px;
    color: var(--accent-text); text-decoration: none; max-width: 100%;
    padding: 2px 6px; border-radius: 3px; border: 1px solid transparent;
  }
  .path-link:hover { background: var(--accent-fill); border-color: var(--accent-fill-strong); }
  .path-link :global(svg) { color: var(--text-faint); flex-shrink: 0; }
  .path-link:hover :global(svg) { color: var(--accent-text); }
  .path-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 380px; }

  .pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px; }
  .meta { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); }
  .controls { display: flex; align-items: center; gap: 10px; }
  .pageidx { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-muted); min-width: 64px; text-align: center; }
</style>
