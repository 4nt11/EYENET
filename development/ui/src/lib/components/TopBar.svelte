<script>
  import Badge from './Badge.svelte';
  import CaseSwitcher from './CaseSwitcher.svelte';
  let { operator = 'op.krieg' } = $props();
</script>

<header>
  <div class="mark">
    <span class="wordmark">EYENET</span>
    <span class="sub">Observation Console</span>
  </div>
  <div class="sep"></div>
  <CaseSwitcher />
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
  .mark { display: flex; align-items: baseline; gap: 8px; }
  .wordmark { font-family: var(--font-mono); font-size: 15px; font-weight: var(--fw-bold); letter-spacing: .16em; color: var(--text); }
  .sub { font-family: var(--font-mono); font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--accent-text); }
  .sep { width: 1px; height: 20px; background: var(--border); }
  .case { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); }
  .right { margin-left: auto; display: flex; align-items: center; gap: 14px; }
  .live { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); }
  .live .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--red-text); }
  .op { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); }
</style>
