import React from 'react';

const KIND = {
  info:     { color: 'var(--text-secondary)', rail: 'var(--border-strong)' },
  observe:  { color: 'var(--accent-text)', rail: 'var(--accent)' },
  alert:    { color: 'var(--red-text)', rail: 'var(--red)' },
  system:   { color: 'var(--text-tertiary)', rail: 'var(--border)' },
};

/**
 * Live event feed item (streaming). Monospace timestamp, left rail by kind, optional label + actor.
 * Set `fresh` to briefly flag a just-arrived event.
 */
export function EventFeedItem({ time, kind = 'info', label, message, source, fresh = false, style }) {
  const k = KIND[kind] || KIND.info;
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '78px 1fr',
      gap: 10,
      padding: '6px 12px 6px 10px',
      borderLeft: `2px solid ${k.rail}`,
      borderBottom: '1px solid var(--border)',
      background: fresh ? 'var(--accent-fill)' : 'transparent',
      transition: 'background 600ms ease',
      ...style,
    }}>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--fs-11)',
        letterSpacing: 'var(--tracking-data)',
        color: 'var(--text-tertiary)',
        lineHeight: 'var(--lh-normal)',
        whiteSpace: 'nowrap',
      }}>
        {time}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          {label ? (
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--fs-11)',
              fontWeight: 'var(--fw-medium)',
              letterSpacing: 'var(--tracking-label)',
              textTransform: 'uppercase',
              color: k.color,
            }}>
              {label}
            </span>
          ) : null}
          <span style={{
            fontFamily: 'var(--font-sans)',
            fontSize: 'var(--fs-13)',
            color: 'var(--text-body)',
            lineHeight: 'var(--lh-normal)',
          }}>
            {message}
          </span>
        </div>
        {source ? (
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 'var(--fs-11)',
            letterSpacing: 'var(--tracking-data)',
            color: 'var(--text-tertiary)',
          }}>
            {source}
          </span>
        ) : null}
      </div>
    </div>
  );
}
