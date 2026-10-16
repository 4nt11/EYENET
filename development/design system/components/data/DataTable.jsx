import React from 'react';

/**
 * Dense, evidence-grade data table. Monospace cells, hairline rows, optional right-alignment.
 * columns: [{ key, header, width?, align?, mono?, render? }]
 */
export function DataTable({ columns = [], rows = [], onRowClick, selectedId, rowKey = 'id', style }) {
  const [hover, setHover] = React.useState(null);
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden', background: 'var(--surface)', ...style }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-sans)' }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                style={{
                  textAlign: c.align || 'left',
                  padding: '8px 12px',
                  width: c.width,
                  fontFamily: 'var(--font-sans)',
                  fontSize: 'var(--fs-11)',
                  fontWeight: 'var(--fw-semibold)',
                  letterSpacing: 'var(--tracking-label)',
                  textTransform: 'uppercase',
                  color: 'var(--text-tertiary)',
                  background: 'var(--panel)',
                  borderBottom: '1px solid var(--border)',
                  whiteSpace: 'nowrap',
                }}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const id = r[rowKey] ?? i;
            const isSel = selectedId != null && id === selectedId;
            const isHover = hover === id;
            return (
              <tr
                key={id}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                onMouseEnter={() => setHover(id)}
                onMouseLeave={() => setHover(null)}
                style={{
                  cursor: onRowClick ? 'pointer' : 'default',
                  background: isSel ? 'var(--accent-fill)' : isHover ? 'var(--panel)' : 'transparent',
                  borderLeft: isSel ? '2px solid var(--accent-text)' : '2px solid transparent',
                }}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    style={{
                      textAlign: c.align || 'left',
                      padding: '7px 12px',
                      fontFamily: c.mono ? 'var(--font-mono)' : 'var(--font-sans)',
                      fontSize: c.mono ? 'var(--fs-12)' : 'var(--fs-13)',
                      letterSpacing: c.mono ? 'var(--tracking-data)' : 'normal',
                      color: 'var(--text-body)',
                      borderBottom: '1px solid var(--border)',
                      whiteSpace: 'nowrap',
                      verticalAlign: 'middle',
                    }}
                  >
                    {c.render ? c.render(r[c.key], r) : r[c.key]}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
