import React from 'react';
import { Badge } from '../status/Badge.jsx';

/**
 * Case summary card for a caseload grid/list. Case id (mono), title, tier badge, meta row.
 */
export function CaseCard({ caseId, title, tier = 'medium', tierLabel, actor, updated, openCount, active = false, onClick, style }) {
  const [hover, setHover] = React.useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: 'var(--radius)',
        background: active ? 'var(--accent-fill)' : hover ? 'var(--panel-2)' : 'var(--panel)',
        padding: '12px 14px',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'background 120ms ease, border-color 120ms ease',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        ...style,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--fs-11)',
          letterSpacing: 'var(--tracking-data)',
          color: 'var(--text-tertiary)',
        }}>
          {caseId}
        </span>
        <Badge tone={tier} dot>{tierLabel || tier}</Badge>
      </div>
      <div style={{
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--fs-14)',
        fontWeight: 'var(--fw-semibold)',
        color: 'var(--text-body)',
        lineHeight: 'var(--lh-tight)',
      }}>
        {title}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        {actor ? (
          <Meta label="Actor" value={actor} mono />
        ) : null}
        {openCount != null ? (
          <Meta label="Open leads" value={String(openCount)} />
        ) : null}
        {updated ? (
          <Meta label="Updated" value={updated} mono />
        ) : null}
      </div>
    </div>
  );
}

function Meta({ label, value, mono }) {
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2 }}>
      <span style={{
        fontFamily: 'var(--font-sans)',
        fontSize: 'var(--fs-11)',
        letterSpacing: 'var(--tracking-label)',
        textTransform: 'uppercase',
        color: 'var(--text-tertiary)',
      }}>{label}</span>
      <span style={{
        fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)',
        fontSize: 'var(--fs-12)',
        letterSpacing: mono ? 'var(--tracking-data)' : 'normal',
        color: 'var(--text-secondary)',
      }}>{value}</span>
    </span>
  );
}
