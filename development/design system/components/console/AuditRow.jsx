import React from 'react';

/**
 * Audit-trail row — immutable action record. Mono timestamp + actor, action verb, target, optional tamper flag.
 * action: { verb, target } | children as free content.
 */
export function AuditRow({ time, actor, verb, target, detail, tamper = false, style, children }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '150px 130px 1fr',
      gap: 12,
      padding: '7px 12px',
      borderBottom: '1px solid var(--border)',
      alignItems: 'baseline',
      background: tamper ? 'var(--red-fill)' : 'transparent',
      ...style,
    }}>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--fs-11)',
        letterSpacing: 'var(--tracking-data)',
        color: 'var(--text-tertiary)',
        whiteSpace: 'nowrap',
      }}>
        {time}
      </span>
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--fs-12)',
        letterSpacing: 'var(--tracking-data)',
        color: tamper ? 'var(--red-text)' : 'var(--accent-text)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}>
        {actor}
      </span>
      <span style={{
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--fs-13)',
        color: 'var(--text-body)',
        lineHeight: 'var(--lh-normal)',
      }}>
        {children ? children : (
          <>
            {tamper ? (
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--fs-11)',
                fontWeight: 'var(--fw-medium)',
                letterSpacing: 'var(--tracking-label)',
                textTransform: 'uppercase',
                color: 'var(--red-text)',
                marginRight: 8,
              }}>TAMPER</span>
            ) : null}
            <span style={{ color: 'var(--text-secondary)' }}>{verb} </span>
            {target ? (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-12)', color: 'var(--text-body)' }}>{target}</span>
            ) : null}
            {detail ? <span style={{ color: 'var(--text-tertiary)' }}> — {detail}</span> : null}
          </>
        )}
      </span>
    </div>
  );
}
