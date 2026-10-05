<script>
  import { goto } from '$app/navigation';
  import Badge from './Badge.svelte';
  import CaseSwitcher from './CaseSwitcher.svelte';
  import { ui, toggleNav } from '$lib/ui.svelte.js';
  let { operator = 'op.krieg' } = $props();

  let query = $state('');
  let searchEl;

  function submitSearch(e) {
    if (e.key !== 'Enter') return;
    const q = query.trim();
    if (q) goto(`/search?q=${encodeURIComponent(q)}`);
  }

  // Press `/` anywhere (unless already typing) to jump to the search box.
  function onKeydown(e) {
    if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target;
    const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
    if (typing) return;
    e.preventDefault();
    searchEl?.focus();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<header>
  <button
    class="navtoggle"
    onclick={toggleNav}
    aria-label={ui.navCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
    aria-pressed={ui.navCollapsed}
    title={ui.navCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
  >
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <line x1="4" y1="7" x2="20" y2="7" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="17" x2="20" y2="17" />
    </svg>
  </button>
  <div class="mark">
    <span class="wordmark">EYENET</span>
    <span class="sub">Observation Console</span>
  </div>
  <div class="sep"></div>
  <CaseSwitcher />
  <input
    class="search"
    type="search"
    bind:this={searchEl}
    bind:value={query}
    onkeydown={submitSearch}
    placeholder="Search everything · press / to focus"
    aria-label="Global search"
    spellcheck="false"
  />
  <div class="right">
    <span class="live"><span class="dot"></span>LIVE</span>
    <Badge tone="neutral" dot>SECURE LINK</Badge>
    <span class="op">{operator}</span>
  </div>
</header>

<style>
  header {
    height: 44px;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 16px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }
  .navtoggle {
    flex: 0 0 auto;
    display: inline-flex; align-items: center; justify-content: center;
    width: 28px; height: 28px; padding: 0;
    background: transparent; border: 1px solid var(--border-strong); border-radius: var(--radius);
    color: var(--text-muted); cursor: pointer;
    transition: border-color 120ms ease, color 120ms ease, background 120ms ease;
  }
  .navtoggle:hover { border-color: var(--accent); color: var(--accent-text); background: var(--panel); }
  .mark { display: flex; align-items: baseline; gap: 8px; flex: 0 0 auto; }
  .wordmark { font-family: var(--font-mono); font-size: 15px; font-weight: var(--fw-bold); letter-spacing: .16em; color: var(--text); }
  .sub { font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--accent-text); }
  .sep { width: 1px; height: 20px; background: var(--border); }
  .case { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .search {
    flex: 1 1 180px;
    min-width: 0;
    max-width: 360px;
    height: 28px;
    padding: 0 10px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius);
    color: var(--text-body);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    letter-spacing: var(--tracking-data);
  }
  .search::placeholder { color: var(--text-faint); }
  .search:focus { outline: none; border-color: var(--accent); }
  .right { flex: 0 0 auto; margin-left: auto; display: flex; align-items: center; gap: 14px; }
  .live { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); }
  .live .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--red-text); }
  .op { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); }
</style>
