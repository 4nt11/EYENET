import React from 'react';

/**
 * Key/value evidence panel. Monospace values, aligned labels, optional copy affordance & title.
 * items: [{ label, value, mono?, tone? }]
 */
export function EvidencePanel({ title, items = [], labelWidth = 128, style }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--panel)', overflow: 'hidden', ...style }}>
      {title ? (
        <div style={{
          padding: '8px 12px',
          fontFamily: 'var(--font-sans)',
          fontSize: 'var(--fs-11)',
          fontWeight: 'var(--fw-semibold)',
          letterSpacing: 'var(--tracking-label)',
          textTransform: 'uppercase',
          color: 'var(--text-tertiary)',
          borderBottom: '1px solid var(--border)',
          background: 'var(--surface)',
        }}>
          {title}
        </div>
      ) : null}
      <dl style={{ margin: 0 }}>
        {items.map((it, i) => (
          <div
            key={i}
            style={{
              display: 'grid',
              gridTemplateColumns: `${labelWidth}px 1fr`,
              gap: 12,
              padding: '7px 12px',
              borderBottom: i === items.length - 1 ? 'none' : '1px solid var(--border)',
              alignItems: 'baseline',
            }}
          >
            <dt style={{
              fontFamily: 'var(--font-sans)',
              fontSize: 'var(--fs-12)',
              color: 'var(--text-tertiary)',
              letterSpacing: '.01em',
            }}>
              {it.label}
            </dt>
            <dd style={{
              margin: 0,
              fontFamily: it.mono === false ? 'var(--font-sans)' : 'var(--font-mono)',
              fontSize: it.mono === false ? 'var(--fs-13)' : 'var(--fs-12)',
              letterSpacing: it.mono === false ? 'normal' : 'var(--tracking-data)',
              color: it.tone === 'critical' ? 'var(--red-text)'
                : it.tone === 'accent' ? 'var(--accent-text)'
                : 'var(--text-body)',
              wordBreak: 'break-all',
            }}>
              {it.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
