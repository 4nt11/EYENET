<script>
  // localStorage JWTs tab, per OG mockup. Hero stat pair + prioritise-
  // revocation banner frames the page: a live JWT skips MFA on the target
  // site until its exp claim elapses, so the operator triages non-expired
  // rows first. Rows expand on click to reveal the DECODED header +
  // payload as pretty JSON (base64url decoded client-side from the raw
  // jwt_value the backend already returns; no signature verification -
  // these are STOLEN tokens, verification is meaningless).
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import Button from '$lib/components/Button.svelte';
  import CaretDown from 'phosphor-svelte/lib/CaretDown';
  import Warning from 'phosphor-svelte/lib/Warning';
  import Key from 'phosphor-svelte/lib/Key';
  import Clock from 'phosphor-svelte/lib/Clock';
  import Copy from 'phosphor-svelte/lib/Copy';
  import { localstorageCtx, loadDomainLocalStorage } from '$lib/stealerByDomain.svelte.js';

  const fmt = (n) => (n ?? 0).toLocaleString();
  const shortSha = (s) => (s ? s.slice(0, 8) : '');
  const relTime = (iso) => {
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
  const absDate = (iso) => {
    if (!iso) return 'unknown';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  };

  let domain = $derived($page.params.domain);
  onMount(() => loadDomainLocalStorage(domain, { page: 1 }));

  let lastDomain = $state(null);
  $effect(() => {
    if (domain && domain !== lastDomain) {
      lastDomain = domain;
      loadDomainLocalStorage(domain, { page: 1 });
    }
  });

  const prev = () => localstorageCtx.page > 1 && loadDomainLocalStorage(domain, { page: localstorageCtx.page - 1 });
  const next = () => localstorageCtx.page < localstorageCtx.pages && loadDomainLocalStorage(domain, { page: localstorageCtx.page + 1 });

  // Earliest live-JWT expiry across the CURRENT PAGE's items. A proper
  // global earliest needs a backend aggregate; for now this answers
  // "what's about to burn out among what I can see" which is usually
  // what the operator wants anyway.
  const earliestLiveExp = $derived.by(() => {
    const now = Date.now();
    let earliest = null;
    for (const r of localstorageCtx.items ?? []) {
      if (r.is_expired || !r.expires_at) continue;
      const t = new Date(r.expires_at).getTime();
      if (t <= now) continue;
      if (earliest === null || t < earliest) earliest = t;
    }
    return earliest ? new Date(earliest).toISOString() : null;
  });

  // Client-side base64url decode. Backend already does this to populate
  // the row columns; we re-decode here so the expansion view can show the
  // FULL header + payload, not just the surfaced sub/iss/aud fields.
  function decodeJwt(token) {
    if (!token) return null;
    try {
      const parts = token.trim().split('.');
      if (parts.length !== 3) return null;
      const pad = (s) => s + '='.repeat((4 - s.length % 4) % 4);
      const b64url = (s) => atob(pad(s).replace(/-/g, '+').replace(/_/g, '/'));
      const header = JSON.parse(b64url(parts[0]));
      const payload = JSON.parse(b64url(parts[1]));
      return { header, payload };
    } catch { return null; }
  }

  // Tiny JSON syntax highlighter: splits JSON.stringify output into
  // key / string / number / boolean / null tokens and wraps each in a
  // span that CSS colours via the design-system tokens. No external
  // deps, same output as JSON.stringify with indent so the operator
  // can copy-paste into jwt.io or a script.
  function highlightJson(obj) {
    const json = JSON.stringify(obj, null, 2);
    return json
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(\.\d*)?([eE][+-]?\d+)?)/g, (m) => {
        let cls = 'num';
        if (/^"/.test(m)) cls = /:$/.test(m) ? 'key' : 'str';
        else if (/true|false/.test(m)) cls = 'bool';
        else if (/null/.test(m)) cls = 'null';
        return `<span class="jsyn-${cls}">${m}</span>`;
      });
  }

  let expanded = $state(new Set());
  function toggleRow(k) {
    const n = new Set(expanded);
    if (n.has(k)) n.delete(k); else n.add(k);
    expanded = n;
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text ?? ''); } catch { /* ignore */ }
  }
</script>

<section class="wrap">
  <div class="url-hint">GET /v1/stealer/by-domain/{domain}/localstorage?page={localstorageCtx.page}&amp;limit={localstorageCtx.limit}</div>

  {#if localstorageCtx.denied}
    <div class="banner-warn">
      You lack the <code>read:stealer</code> clearance. Request a grant from
      an operator with <code>admin:stealer</code> rights.
    </div>
  {:else if localstorageCtx.error}
    <div class="banner-error">{localstorageCtx.error}</div>
  {:else if localstorageCtx.loaded && localstorageCtx.items.length === 0}
    <div class="empty">
      No localStorage JWTs captured for <code>{domain}</code>.
    </div>
  {:else}
    <div class="hero-grid">
      <div class="hero-tile">
        <div class="hero-label"><Key size={12} weight="regular" /> LIVE JWTS</div>
        <div class="hero-value" class:has-live={localstorageCtx.live_count > 0}>
          {fmt(localstorageCtx.live_count)} <span class="hero-total">/ {fmt(localstorageCtx.total)}</span>
        </div>
      </div>
      <div class="hero-tile">
        <div class="hero-label"><Clock size={12} weight="regular" /> EARLIEST EXPIRY</div>
        <div class="hero-value hero-date">{absDate(earliestLiveExp)}</div>
      </div>
    </div>

    {#if localstorageCtx.live_count > 0}
      <div class="alert-banner">
        <Warning size={16} weight="regular" />
        <span>{fmt(localstorageCtx.live_count)} live JWTs leaked. These bypass MFA on the target site until their exp claim elapses. Prioritize revocation.</span>
      </div>
    {/if}

    <div class="table-wrap">
      <table class="jwts">
        <thead>
          <tr>
            <th>Host</th>
            <th>Key</th>
            <th>Subject</th>
            <th>Issuer</th>
            <th>Alg</th>
            <th>Expires</th>
            <th>Archive</th>
            <th>Victim</th>
            <th class="chev-col" aria-label="expand"></th>
          </tr>
        </thead>
        <tbody>
          {#each localstorageCtx.items as r, i (`${r.archive_sha256}:${r.victim_folder}:${r.host}:${r.key}:${i}`)}
            {@const rowKey = `${r.archive_sha256}:${r.victim_folder}:${r.host}:${r.key}:${i}`}
            {@const isOpen = expanded.has(rowKey)}
            {@const decoded = isOpen ? decodeJwt(r.jwt_value) : null}
            {@const weakAlg = r.jwt_algorithm && /^(none|HS1|HS224|RS1)$/i.test(r.jwt_algorithm)}
            <tr class="jwt-row" class:live={!r.is_expired} class:expired={r.is_expired} class:open={isOpen} onclick={() => toggleRow(rowKey)}>
              <td class="mono host" title={r.host}>{r.host}</td>
              <td class="mono key" title={r.key}>{r.key}</td>
              <td class="mono subject" title={r.jwt_subject ?? ''}>
                {#if r.jwt_subject}{r.jwt_subject}{:else}<span class="nulltxt">null</span>{/if}
              </td>
              <td class="mono issuer" title={r.jwt_issuer ?? ''}>
                {#if r.jwt_issuer}{r.jwt_issuer}{:else}<span class="nulltxt">null</span>{/if}
              </td>
              <td class="alg-cell">
                {#if r.jwt_algorithm}
                  <span class="alg-chip" class:weak={weakAlg}>{r.jwt_algorithm}</span>
                {:else}
                  <span class="alg-chip weak">none</span>
                {/if}
              </td>
              <td class="mono exp" class:exp-expired={r.is_expired} class:exp-live={!r.is_expired && r.expires_at}>
                {#if r.expires_at}{relTime(r.expires_at)}{:else}<span class="nulltxt">unknown</span>{/if}
              </td>
              <td class="mono sha" title={r.archive_sha256}>{shortSha(r.archive_sha256)}</td>
              <td class="mono victim" title={r.victim_folder}>{r.victim_folder}</td>
              <td class="chev-col">
                <span class="chev" class:open={isOpen}><CaretDown size={14} weight="regular" /></span>
              </td>
            </tr>
            {#if isOpen}
              <tr class="expand-row" class:live={!r.is_expired} class:expired={r.is_expired}>
                <td colspan="9">
                  <div class="expand-inner">
                    <div class="expand-head">
                      <span class="expand-label">DECODED CLAIMS</span>
                      <button type="button" class="copy-btn" onclick={(e) => { e.stopPropagation(); copy(r.jwt_value); }}>
                        <Copy size={11} weight="regular" />
                        <span>Copy JWT ({(r.jwt_value || '').slice(0, 18)}...)</span>
                      </button>
                    </div>
                    {#if decoded}
                      <pre class="json">{@html highlightJson(decoded)}</pre>
                    {:else}
                      <div class="decode-fail">Decode failed. Malformed JWT or not three base64url segments.</div>
                    {/if}
                    <div class="expand-foot">
                      <span class="ef-label">archive</span> <span class="mono">{r.archive_sha256}</span>
                    </div>
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>

    <div class="pager">
      <div class="meta">Showing {fmt(localstorageCtx.items.length)} of {fmt(localstorageCtx.total)}</div>
      <div class="controls">
        <Button variant="ghost" onclick={prev} disabled={localstorageCtx.page <= 1 || localstorageCtx.loading}>Prev</Button>
        <span class="pageidx">{fmt(localstorageCtx.page)} / {fmt(localstorageCtx.pages)}</span>
        <Button variant="ghost" onclick={next} disabled={localstorageCtx.page >= localstorageCtx.pages || localstorageCtx.loading}>Next</Button>
      </div>
    </div>
  {/if}
</section>

<style>
  .wrap { display: flex; flex-direction: column; gap: 14px; }
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

  /* Hero: two-tile grid with a shared hairline, mirror of the Domain View
     hero's shared-hairline pattern. Live / earliest expiry are the two
     numbers the operator cares about before touching the table. */
  .hero-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 1px;
    border: 1px solid var(--border); background: var(--border); border-radius: 4px; overflow: hidden;
  }
  .hero-tile {
    background: var(--surface); padding: 14px 18px 16px; display: flex; flex-direction: column; gap: 8px;
  }
  .hero-label {
    display: inline-flex; align-items: center; gap: 6px;
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-medium);
    color: var(--text-muted); text-transform: uppercase; letter-spacing: var(--tracking-label);
  }
  .hero-value { font-family: var(--font-mono); font-size: 28px; letter-spacing: -0.02em; color: var(--text); }
  .hero-value.has-live { color: var(--red-text); }
  .hero-total { color: var(--text-muted); font-size: 20px; }
  .hero-date { font-size: 22px; color: var(--text); }

  /* Warning banner: amber fill, warning glyph, sits between hero + table. */
  .alert-banner {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; border: 1px solid var(--warn-fill-strong, var(--warn-fill));
    background: var(--warn-fill); color: var(--warn-text);
    font-family: var(--font-sans); font-size: var(--fs-13); border-radius: 3px;
  }
  .alert-banner :global(svg) { flex-shrink: 0; }

  .table-wrap { border: 1px solid var(--border); border-radius: 4px; }
  table.jwts { width: 100%; border-collapse: collapse; }
  table.jwts th, table.jwts td {
    padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: left;
    font-family: var(--font-sans); font-size: var(--fs-12);
  }
  table.jwts thead th {
    background: var(--panel); color: var(--text-muted); font-weight: var(--fw-medium);
    text-transform: uppercase; font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    position: sticky; top: 0; z-index: 1;
  }
  table.jwts tr:last-child td { border-bottom: 0; }

  /* Clickable rows. Live rows carry a 3px red stripe on the left edge via
     an inset box-shadow so column widths stay aligned (border-left shifts
     the first td). Expired rows render flat. */
  .jwt-row { cursor: pointer; }
  .jwt-row.live td:first-child { box-shadow: inset 3px 0 0 var(--red-text); }
  .jwt-row:hover td { background: rgba(255,255,255,0.015); }
  .jwt-row.expired td.host, .jwt-row.expired td.key { color: var(--text-faint); }
  .jwt-row.expired td { opacity: 0.8; }
  .jwt-row.open td { background: rgba(255,255,255,0.02); border-bottom-color: transparent; }

  .mono { font-family: var(--font-mono); font-size: var(--fs-12); }
  td.host { color: var(--text); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.key { color: var(--text-body); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.subject { color: var(--accent-text); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.issuer { color: var(--text-body); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td.alg-cell { width: 70px; }
  td.exp { width: 110px; color: var(--text-muted); }
  td.exp.exp-live { color: var(--text-ok, #5bbf80); }
  td.exp.exp-expired { color: var(--red-text); }
  td.sha { color: var(--text-muted); width: 110px; }
  td.victim { color: var(--text-muted); max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  th.chev-col, td.chev-col { width: 36px; text-align: right; }
  .chev { color: var(--text-muted); display: inline-flex; transition: transform 150ms ease; transform: rotate(-90deg); }
  .chev.open { transform: rotate(0deg); color: var(--text-body); }

  .alg-chip {
    display: inline-flex; align-items: center;
    padding: 1px 7px; border: 1px solid var(--accent-fill-strong); border-radius: 10px;
    background: var(--accent-fill); color: var(--accent-text);
    font-family: var(--font-mono); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .alg-chip.weak {
    background: var(--warn-fill); color: var(--warn-text);
    border-color: var(--warn-fill-strong, var(--warn-fill));
  }
  .nulltxt { font-family: var(--font-sans); font-style: italic; color: var(--text-faint); font-size: var(--fs-11); }

  /* Expansion row: same red stripe as the parent row. The expand-inner
     box frames the decoded JSON in a slightly recessed panel. */
  tr.expand-row td { padding: 0; }
  tr.expand-row.live td { box-shadow: inset 3px 0 0 var(--red-text); }
  .expand-inner {
    padding: 14px 18px 18px; background: rgba(255,255,255,0.01); display: flex; flex-direction: column; gap: 10px;
  }
  .expand-head {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
  }
  .expand-label {
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-medium);
    color: var(--text-muted); text-transform: uppercase; letter-spacing: var(--tracking-label);
  }
  .copy-btn {
    appearance: none; display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border: 1px solid var(--border); border-radius: 3px;
    background: transparent; color: var(--text-body);
    font-family: var(--font-mono); font-size: var(--fs-11); cursor: pointer;
  }
  .copy-btn:hover { background: var(--accent-fill); border-color: var(--accent-fill-strong); color: var(--accent-text); }
  .copy-btn :global(svg) { color: var(--text-faint); }
  .copy-btn:hover :global(svg) { color: var(--accent-text); }

  .json {
    margin: 0; padding: 14px 18px; background: var(--panel); border-radius: 3px;
    border: 1px solid var(--border);
    font-family: var(--font-mono); font-size: var(--fs-12); line-height: 1.55;
    color: var(--text-body); white-space: pre; overflow-x: auto;
  }
  /* Simple regex-tokenised JSON highlighting. Design system tokens only. */
  .json :global(.jsyn-key) { color: var(--accent-text); }
  .json :global(.jsyn-str) { color: var(--text-ok, #5bbf80); }
  .json :global(.jsyn-num) { color: var(--text); }
  .json :global(.jsyn-bool) { color: var(--warn-text); }
  .json :global(.jsyn-null) { color: var(--text-faint); font-style: italic; }

  .decode-fail {
    padding: 10px 14px; border: 1px dashed var(--border); border-radius: 3px;
    color: var(--text-faint); font-family: var(--font-sans); font-size: var(--fs-12); font-style: italic;
  }
  .expand-foot {
    display: flex; align-items: center; gap: 8px;
    font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint);
  }
  .ef-label { text-transform: uppercase; letter-spacing: var(--tracking-label); }

  .pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 4px; }
  .meta { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-13); }
  .controls { display: flex; align-items: center; gap: 10px; }
  .pageidx { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-muted); min-width: 64px; text-align: center; }
</style>
