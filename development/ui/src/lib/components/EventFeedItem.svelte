<script>
  // Live event feed row. kind sets the left rail + label color. `fresh` briefly flashes purple.
  const KIND = {
    info:    { color: 'var(--text-secondary)', rail: 'var(--border-strong)' },
    observe: { color: 'var(--accent-text)',    rail: 'var(--accent)' },
    alert:   { color: 'var(--red-text)',       rail: 'var(--red)' },
    system:  { color: 'var(--text-faint)',     rail: 'var(--border)' }
  };
  let { time, kind = 'info', label, message, source, fresh = false } = $props();
  let k = $derived(KIND[kind] ?? KIND.info);
</script>

<div class="item" class:fresh style="border-left-color:{k.rail};">
  <span class="time">{time}</span>
  <div class="body">
    <div class="line">
      {#if label}<span class="label" style="color:{k.color};">{label}</span>{/if}
      <span class="msg">{message}</span>
    </div>
    {#if source}<span class="source">{source}</span>{/if}
  </div>
</div>

<style>
  .item {
    display: grid;
    grid-template-columns: 78px 1fr;
    gap: 10px;
    padding: 6px 12px 6px 10px;
    border-left: 2px solid;
    border-bottom: 1px solid var(--border);
    background: transparent;
    transition: background 600ms ease;
  }
  .item.fresh { background: var(--accent-fill); }
  .time {
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    letter-spacing: var(--tracking-data);
    color: var(--text-faint);
    line-height: var(--lh-normal);
    white-space: nowrap;
  }
  .body { min-width: 0; }
  .line { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .label {
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    font-weight: var(--fw-medium);
    letter-spacing: var(--tracking-label);
    text-transform: uppercase;
  }
  .msg { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); }
  .source { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
</style>
