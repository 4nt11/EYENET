<script>
  // Victim-autofills tab. Semantics: the autofill table in Chromium carries
  // no URL, so a domain-filtered view is impossible. Instead we show every
  // autofill from victims that also leaked to this domain -- what the same
  // compromised machines typed into forms anywhere. Email + phone + address
  // overlap is the operator value here: pivot from "google.com leak" to
  // "the full identity surface of the people caught in it".
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import Button from '$lib/components/Button.svelte';
  import Copy from 'phosphor-svelte/lib/Copy';
  import { autofillsCtx, loadDomainAutofills } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const shortSha = (s) => (s ? s.slice(0, 8) + s.slice(-4) : '');
  const cleanVal = (s) => (s ?? '').replace(/\r?\n/g, '').trim();

  let domain = $derived($page.params.domain);


  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainAutofills(domain, { page: 1 });
    }
  });

  const prev = () => autofillsCtx.page > 1 && loadDomainAutofills(domain, { page: autofillsCtx.page - 1 });
  const next = () => autofillsCtx.page < autofillsCtx.pages && loadDomainAutofills(domain, { page: autofillsCtx.page + 1 });

  async function copy(text) {
    try { await navigator.clipboard.writeText(cleanVal(text)); } catch { /* ignore */ }
  }
</script>

<section class="wrap">
  <div class="url-hint-row">
    <div class="url-hint">GET /v1/stealer/by-domain/{domain}/autofills?page={autofillsCtx.page}&amp;limit={autofillsCtx.limit}</div>
    <div class="scope-note">from victims that leaked to <code>{domain}</code></div>
  </div>

  {#if autofillsCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if autofillsCtx.error}
    <div class="banner-error">{autofillsCtx.error}</div>
  {:else if autofillsCtx.loaded && autofillsCtx.items.length === 0}
    <div class="empty">
      No autofills captured from victims of <code>{domain}</code>.
    </div>
  {:else}
    <div class="table-wrap">
      <table class="autofills">
        <thead>
          <tr>
            <th>Field</th>
            <th>Value</th>
            <th>Archive</th>
            <th>Victim</th>
          </tr>
        </thead>
        <tbody>
          {#each autofillsCtx.items as r, i (`${r.archive_sha256}:${r.victim_folder}:${r.field_name}:${i}`)}
            <tr>
              <td class="mono field" title={r.field_name}>{r.field_name}</td>
              <td class="val">
                <button type="button" class="val-btn" title="Copy value" onclick={() => copy(r.value)}>
                  <span class="val-text">{cleanVal(r.value)}</span>
                  <Copy size={11} weight="regular" />
                </button>
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
        Showing {fmt(autofillsCtx.items.length)} of {fmt(autofillsCtx.total)}
      </div>
      <div class="controls">
        <Button variant="ghost" onclick={prev} disabled={autofillsCtx.page <= 1 || autofillsCtx.loading}>Prev</Button>
        <span class="pageidx">{fmt(autofillsCtx.page)} / {fmt(autofillsCtx.pages)}</span>
        <Button variant="ghost" onclick={next} disabled={autofillsCtx.page >= autofillsCtx.pages || autofillsCtx.loading}>Next</Button>
      </div>
    </div>
  {/if}
</section>

<style>
  .wrap { display: flex; flex-direction: column; gap: 18px; }
  .url-hint-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .url-hint { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .scope-note { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); font-style: italic; }
  .scope-note code { font-family: var(--font-mono); font-style: normal; color: var(--text-body); }

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

  table.autofills { width: 100%; border-collapse: collapse; }
  table.autofills th, table.autofills td {
    padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: left;
    font-family: var(--font-sans); font-size: var(--fs-12);
  }
  table.autofills thead th {
    background: var(--panel); color: var(--text-muted); font-weight: var(--fw-medium);
    text-transform: uppercase; font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    position: sticky; top: 0; z-index: 1;
  }
  table.autofills tr:last-child td { border-bottom: 0; }
  table.autofills tr:hover td { background: rgba(255,255,255,0.015); }

  .mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  td.field { color: var(--accent-text); width: 180px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.val { max-width: 520px; }
  td.sha { color: var(--text-muted); width: 130px; }
  td.victim { color: var(--text-muted); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .val-btn {
    appearance: none; background: transparent; border: 1px solid transparent;
    padding: 2px 6px; border-radius: 3px; cursor: pointer;
    display: inline-flex; align-items: center; gap: 6px;
    color: var(--text-body); font-family: var(--font-mono); font-size: var(--fs-12);
    max-width: 100%; text-align: left;
  }
  .val-btn:hover { border-color: var(--accent-fill-strong); background: var(--accent-fill); color: var(--accent-text); }
  .val-btn :global(svg) { color: var(--text-faint); flex-shrink: 0; }
  .val-btn:hover :global(svg) { color: var(--accent-text); }
  .val-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 480px; }

  .pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px; }
  .meta { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); }
  .controls { display: flex; align-items: center; gap: 10px; }
  .pageidx { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-muted); min-width: 64px; text-align: center; }
</style>
