<script>
  // Domain View landing. Operator knows what they're doing; just give them the
  // input + recent-history list. Canonicalisation + scope rules live in the
  // layout once a domain is picked.
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import Globe from 'phosphor-svelte/lib/Globe';
  import MagnifyingGlass from 'phosphor-svelte/lib/MagnifyingGlass';

  const RECENT_KEY = 'eyenet.by-domain.recent';
  const RECENT_MAX = 8;

  let raw = $state('');
  let busy = $state(false);
  let recent = $state([]);

  function readRecent() {
    try {
      const j = localStorage.getItem(RECENT_KEY);
      if (!j) return [];
      const parsed = JSON.parse(j);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function writeRecent(list) {
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* ignore */ }
  }

  function pushRecent(entry) {
    const existing = readRecent().filter((r) => r.raw !== entry.raw);
    const next = [entry, ...existing].slice(0, RECENT_MAX);
    writeRecent(next);
    recent = next;
  }

  const looksPlausible = $derived(
    raw.trim().length > 0 && /[.]/.test(raw.trim())
  );

  async function submit() {
    if (!looksPlausible || busy) return;
    const value = raw.trim();
    busy = true;
    try {
      pushRecent({ raw: value, ts: Date.now() });
      await goto(`/stealer/by-domain/${encodeURIComponent(value)}/credentials`);
    } finally {
      busy = false;
    }
  }

  onMount(() => { recent = readRecent(); });

  function clearRecent() { writeRecent([]); recent = []; }

  function fmtAge(ts) {
    const diff = (Date.now() - ts) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
    return `${Math.round(diff / 86400)}d ago`;
  }
</script>

<main>
  <div class="slug">00 &middot; SEARCH &middot; /domains</div>

  <section class="card">
    <h1>Domain view</h1>
    <p class="sub">
      Enter a domain or URL. Queries are normalised to the registrable domain; subdomains are included.
    </p>

    <form class="search" onsubmit={(e) => { e.preventDefault(); submit(); }}>
      <div class="input-wrap">
        <Globe size={16} weight="regular" />
        <input
          type="text"
          class="input"
          placeholder="www.test.com"
          bind:value={raw}
          autocomplete="off"
          autocapitalize="none"
          spellcheck="false"
          autofocus
        />
      </div>
      <button type="submit" class="btn" disabled={!looksPlausible || busy}>
        <MagnifyingGlass size={14} weight="regular" />
        <span>{busy ? 'Opening' : 'View domain'}</span>
      </button>
    </form>

    {#if recent.length > 0}
      <div class="recent-head">
        <span class="recent-label">RECENT</span>
        <button type="button" class="recent-clear" onclick={clearRecent}>clear</button>
      </div>
      <ul class="recent">
        {#each recent as r (r.raw)}
          <li>
            <a href={`/stealer/by-domain/${encodeURIComponent(r.raw)}/credentials`} class="recent-row" data-sveltekit-reload>
              <span class="recent-dom">{r.raw}</span>
              <span class="recent-age">{fmtAge(r.ts)}</span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</main>

<style>
  main {
    flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center;
    padding: 40px 20px; background: var(--black); position: relative;
  }
  .slug {
    position: absolute; top: 20px; left: 20px;
    font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint);
    letter-spacing: var(--tracking-data); text-transform: uppercase;
  }

  .card {
    width: 100%; max-width: 720px; margin-top: 10vh;
    display: flex; flex-direction: column; gap: 14px;
  }
  h1 {
    margin: 0; font-family: var(--font-sans); font-size: var(--fs-22);
    font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight);
  }
  .sub {
    margin: 0; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-muted);
  }

  .search { display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-top: 4px; }

  .input-wrap {
    position: relative; display: flex; align-items: center;
    border: 1px solid var(--border); background: var(--panel); border-radius: 3px;
    padding-left: 10px; transition: border-color 120ms ease;
  }
  .input-wrap:focus-within { border-color: var(--accent); }
  .input-wrap :global(svg) { color: var(--text-faint); }
  .input {
    flex: 1; padding: 10px 12px; background: transparent; border: 0; outline: 0;
    color: var(--text); font-family: var(--font-mono); font-size: var(--fs-13);
  }

  .btn {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 0 14px; background: var(--accent); color: #fff; border: 0; border-radius: 3px;
    font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-medium);
    cursor: pointer; transition: background 120ms ease;
  }
  .btn:hover { background: var(--accent-hover); }
  .btn:disabled { background: var(--panel-2); color: var(--text-faint); cursor: not-allowed; }
  .btn :global(svg) { flex: 0 0 auto; }

  .recent-head {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-top: 10px;
  }
  .recent-label {
    font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint);
    text-transform: uppercase; letter-spacing: var(--tracking-label);
  }
  .recent-clear {
    appearance: none; background: transparent; border: 0;
    color: var(--text-faint); font-family: var(--font-mono); font-size: var(--fs-11);
    cursor: pointer; padding: 0;
  }
  .recent-clear:hover { color: var(--accent-text); }

  .recent { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border); border-radius: 3px; overflow: hidden; }
  .recent li + li { border-top: 1px solid var(--border); }
  .recent-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; text-decoration: none;
    font-family: var(--font-mono); font-size: var(--fs-12);
    color: var(--text); background: transparent;
  }
  .recent-row:hover { background: rgba(255,255,255,0.02); }
  .recent-dom { color: var(--text); }
  .recent-age { color: var(--text-faint); }
</style>
