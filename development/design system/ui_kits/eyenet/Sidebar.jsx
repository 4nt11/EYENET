const { CaseCard } = window.EYENETDesignSystem_6752a5;

const CASES = [
  { caseId: 'CASE-2026-0417', title: 'Loader campaign — EMEA finance sector', tier: 'critical', tierLabel: 'Critical', actor: 'UNC-3312', openCount: 7, updated: '12:04Z' },
  { caseId: 'CASE-2026-0402', title: 'Credential harvest — supplier portal', tier: 'high', tierLabel: 'High', actor: 'UNC-2980', openCount: 3, updated: '09:51Z' },
  { caseId: 'CASE-2026-0388', title: 'Beaconing host — staging network', tier: 'medium', tierLabel: 'Medium', actor: 'unattributed', openCount: 1, updated: 'Sep 18' },
  { caseId: 'CASE-2026-0371', title: 'Phishing infra teardown', tier: 'low', tierLabel: 'Low', actor: 'UNC-2980', openCount: 0, updated: 'Sep 15' },
];

function Sidebar({ selected, onSelect }) {
  return (
    <aside style={{
      width: 320, flex: '0 0 auto',
      display: 'flex', flexDirection: 'column',
      background: 'var(--black)',
      borderRight: '1px solid var(--border)',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '10px 14px', flex: '0 0 auto',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: '1px solid var(--border)',
      }}>
        <span style={{
          fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600,
          letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-faint)',
        }}>Caseload</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-faint)' }}>{CASES.length} active</span>
      </div>
      <div style={{ overflow: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {CASES.map((c) => (
          <CaseCard key={c.caseId} {...c} active={c.caseId === selected} onClick={() => onSelect(c.caseId)} />
        ))}
      </div>
    </aside>
  );
}
window.Sidebar = Sidebar;
