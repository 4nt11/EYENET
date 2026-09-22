<script>
  // Marks a screen that has no backend API yet. Calm accent strip, never red.
  let { children } = $props();
</script>

<div class="banner">
  <span class="tag">○ Planned</span>
  <span class="msg">{@render children?.()}</span>
</div>

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 20px;
    background: var(--accent-fill);
    border-bottom: 1px solid var(--border);
    flex: 0 0 auto;
  }
  .tag { font-family: var(--font-mono); font-size: var(--fs-11); font-weight: var(--fw-medium); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--accent-text); white-space: nowrap; }
  .msg { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-secondary); line-height: var(--lh-normal); }
</style>
