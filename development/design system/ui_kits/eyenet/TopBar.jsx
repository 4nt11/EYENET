const { Badge } = window.EYENETDesignSystem_6752a5;

function TopBar({ caseId }) {
  return (
    <header style={{
      height: 44, flex: '0 0 auto',
      display: 'flex', alignItems: 'center', gap: 16,
      padding: '0 16px',
      background: 'var(--surface)',
      borderBottom: '1px solid var(--border)',
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700,
          letterSpacing: '.16em', color: 'var(--text)',
        }}>EYENET</span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.14em',
          textTransform: 'uppercase', color: 'var(--accent-text)',
        }}>Observation Console</span>
      </div>
      <div style={{ width: 1, height: 20, background: 'var(--border)' }} />
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-faint)' }}>{caseId}</span>
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--red-text)' }} />LIVE
        </span>
        <Badge tone="neutral" dot>SECURE LINK</Badge>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-text)' }}>op.krieg</span>
      </div>
    </header>
  );
}
window.TopBar = TopBar;
