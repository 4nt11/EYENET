<script>
  // Single metric tile: uppercase micro-label + large mono value + optional unit/sub.
  // tone: 'default' | 'accent' | 'critical' colors the value.
  let { label, value, unit, sub, tone = 'default' } = $props();
  const color = tone === 'critical' ? 'var(--red-text)' : tone === 'accent' ? 'var(--accent-text)' : 'var(--text)';
</script>

<div class="tile">
  <span class="label">{label}</span>
  <span class="value" style="color:{color};">{value}{#if unit}<span class="unit">{unit}</span>{/if}</span>
  {#if sub}<span class="sub">{sub}</span>{/if}
</div>

<style>
  .tile {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
    min-width: 0;
  }
  .label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .value { font-family: var(--font-mono); font-size: var(--fs-22); font-weight: var(--fw-medium); letter-spacing: var(--tracking-data); line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .unit { font-size: var(--fs-13); color: var(--text-muted); margin-left: 3px; }
  .sub { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
</style>
