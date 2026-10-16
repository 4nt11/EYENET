import React from 'react';

/* Classification tiers & statuses. Red reserved for the top severity only. */
const TONES = {
  critical: { color: 'var(--red-text)', fill: 'var(--red-fill)', border: 'rgba(194,69,63,.45)' },
  high:     { color: 'var(--accent-text)', fill: 'var(--accent-fill)', border: 'rgba(162,89,196,.40)' },
  medium:   { color: 'var(--text-body)', fill: 'var(--panel-2)', border: 'var(--border-strong)' },
  low:      { color: 'var(--text-secondary)', fill: 'transparent', border: 'var(--border)' },
  neutral:  { color: 'var(--text-secondary)', fill: 'transparent', border: 'var(--border)' },
};

/**
 * Status / classification tier badge. Monospace, uppercase, 1px hairline. `critical` is the only red tone.
 */
export function Badge({ tone = 'neutral', dot = false, children, style, ...rest }) {
  const t = TONES[tone] || TONES.neutral;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        height: 18,
        padding: '0 7px',
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--fs-11)',
        fontWeight: 'var(--fw-medium)',
        lineHeight: 1,
        letterSpacing: 'var(--tracking-label)',
        textTransform: 'uppercase',
        color: t.color,
        background: t.fill,
        border: `1px solid ${t.border}`,
        borderRadius: 'var(--radius-sm)',
        whiteSpace: 'nowrap',
        ...style,
      }}
      {...rest}
    >
      {dot ? (
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: t.color, flex: '0 0 auto' }} />
      ) : null}
      {children}
    </span>
  );
}
