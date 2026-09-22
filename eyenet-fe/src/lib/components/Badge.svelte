<script>
  // Classification tier / status pill. `critical` is the only red tone.
  const TONES = {
    critical: { color: 'var(--red-text)',       fill: 'var(--red-fill)',    border: 'rgba(194,69,63,.45)' },
    warn:     { color: 'var(--warn-text)',      fill: 'var(--warn-fill)',   border: 'rgba(194,154,63,.45)' },
    high:     { color: 'var(--accent-text)',    fill: 'var(--accent-fill)', border: 'rgba(162,89,196,.40)' },
    medium:   { color: 'var(--text-body)',      fill: 'var(--panel-2)',     border: 'var(--border-strong)' },
    low:      { color: 'var(--text-secondary)', fill: 'transparent',        border: 'var(--border)' },
    neutral:  { color: 'var(--text-secondary)', fill: 'transparent',        border: 'var(--border)' }
  };
  let { tone = 'neutral', dot = false, children } = $props();
  let t = $derived(TONES[tone] ?? TONES.neutral);
</script>

<span class="badge" style="color:{t.color}; background:{t.fill}; border-color:{t.border};">
  {#if dot}<span class="dot" style="background:{t.color}"></span>{/if}
  {@render children?.()}
</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 18px;
    padding: 0 7px;
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    font-weight: var(--fw-medium);
    line-height: 1;
    letter-spacing: var(--tracking-label);
    text-transform: uppercase;
    border: 1px solid;
    border-radius: var(--radius-sm);
    white-space: nowrap;
  }
  .dot { width: 5px; height: 5px; border-radius: 50%; flex: 0 0 auto; }
</style>
