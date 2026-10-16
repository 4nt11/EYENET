import React from 'react';

const VARIANTS = {
  primary: {
    background: 'var(--accent)',
    color: '#fff',
    border: '1px solid var(--accent)',
    hoverBg: 'var(--accent-hover)',
  },
  destructive: {
    background: 'var(--red)',
    color: '#fff',
    border: '1px solid var(--red)',
    hoverBg: 'var(--red-hover)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-body)',
    border: '1px solid var(--border-strong)',
    hoverBg: 'var(--panel-2)',
  },
  quiet: {
    background: 'transparent',
    color: 'var(--text-secondary)',
    border: '1px solid transparent',
    hoverBg: 'var(--panel)',
  },
};

const SIZES = {
  sm: { height: 26, padding: '0 10px', fontSize: 'var(--fs-12)' },
  md: { height: 32, padding: '0 14px', fontSize: 'var(--fs-13)' },
  lg: { height: 38, padding: '0 18px', fontSize: 'var(--fs-14)' },
};

/**
 * Console action button. Primary = purple, destructive = red, everything else quiet/ghost.
 */
export function Button({
  variant = 'quiet',
  size = 'md',
  disabled = false,
  icon = null,
  children,
  onClick,
  type = 'button',
  style,
  ...rest
}) {
  const v = VARIANTS[variant] || VARIANTS.quiet;
  const s = SIZES[size] || SIZES.md;
  const [hover, setHover] = React.useState(false);

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        height: s.height,
        padding: s.padding,
        fontFamily: 'var(--font-sans)',
        fontSize: s.fontSize,
        fontWeight: 'var(--fw-medium)',
        lineHeight: 1,
        letterSpacing: '.01em',
        color: v.color,
        background: hover && !disabled ? v.hoverBg : v.background,
        border: v.border,
        borderRadius: 'var(--radius)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        transition: 'background 120ms ease, border-color 120ms ease',
        whiteSpace: 'nowrap',
        ...style,
      }}
      {...rest}
    >
      {icon ? <span style={{ display: 'inline-flex', width: 14, height: 14 }}>{icon}</span> : null}
      {children}
    </button>
  );
}
