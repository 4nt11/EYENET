<script>
  // Single metric tile: uppercase micro-label + large mono value + optional unit/sub.
  // tone: 'default' | 'accent' | 'critical' colors the value.
  // loader: when truthy, renders a small spinning CircleNotch next to the value.
  //         Used by live-data surfaces (Domain View hero) to signal that the
  //         number is streaming from a reindexing corpus.
  import CircleNotch from 'phosphor-svelte/lib/CircleNotch';
  let { label, value, unit, sub, tone = 'default', loader = false, icon: Icon = null } = $props();
  const color = tone === 'critical' ? 'var(--red-text)' : tone === 'accent' ? 'var(--accent-text)' : 'var(--text)';
</script>

<div class="tile">
  <span class="label">
    {#if Icon}<Icon size={12} weight="regular" />{/if}
    {label}
  </span>
  <span class="value" style="color:{color};">
    {value}{#if unit}<span class="unit">{unit}</span>{/if}
    {#if loader}<span class="spin"><CircleNotch size={14} weight="regular" /></span>{/if}
  </span>
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
  .label { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .label :global(svg) { flex: 0 0 auto; color: var(--text-faint); }
  .value { display: inline-flex; align-items: baseline; gap: 6px; font-family: var(--font-mono); font-size: var(--fs-22); font-weight: var(--fw-medium); letter-spacing: var(--tracking-data); line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .unit { font-size: var(--fs-13); color: var(--text-muted); margin-left: 3px; }
  .sub { display: block; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); font-weight: var(--fw-regular); margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .spin { display: inline-flex; align-items: center; color: var(--accent-text); animation: spin 1.6s linear infinite; }
  @keyframes spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }
</style>
