<script>
  // Console action button. primary = purple, destructive = red, else ghost/quiet.
  const VARIANTS = {
    primary:     { bg: 'var(--accent)',   fg: '#fff',              bd: 'var(--accent)',        hover: 'var(--accent-hover)' },
    destructive: { bg: 'var(--red)',      fg: '#fff',              bd: 'var(--red)',           hover: 'var(--red-hover)' },
    ghost:       { bg: 'transparent',     fg: 'var(--text-body)',  bd: 'var(--border-strong)', hover: 'var(--panel-2)' },
    quiet:       { bg: 'transparent',     fg: 'var(--text-secondary)', bd: 'transparent',      hover: 'var(--panel)' }
  };
  const SIZES = {
    sm: { h: '26px', pad: '0 10px', fs: 'var(--fs-12)' },
    md: { h: '32px', pad: '0 14px', fs: 'var(--fs-13)' },
    lg: { h: '38px', pad: '0 18px', fs: 'var(--fs-14)' }
  };

  let { variant = 'quiet', size = 'md', disabled = false, type = 'button', onclick, children } = $props();

  let v = $derived(VARIANTS[variant] ?? VARIANTS.quiet);
  let s = $derived(SIZES[size] ?? SIZES.md);
</script>

<button
  {type}
  {disabled}
  {onclick}
  style="--_bg:{v.bg}; --_fg:{v.fg}; --_bd:{v.bd}; --_hover:{v.hover}; height:{s.h}; padding:{s.pad}; font-size:{s.fs};"
>
  {@render children?.()}
</button>

<style>
  button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    font-family: var(--font-sans);
    font-weight: var(--fw-medium);
    line-height: 1;
    letter-spacing: .01em;
    white-space: nowrap;
    color: var(--_fg);
    background: var(--_bg);
    border: 1px solid var(--_bd);
    border-radius: var(--radius);
    cursor: pointer;
    transition: background 120ms ease, border-color 120ms ease;
  }
  button:hover:not(:disabled) { background: var(--_hover); }
  button:disabled { opacity: .45; cursor: not-allowed; }
</style>
