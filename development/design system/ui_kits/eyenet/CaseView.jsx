const { DataTable, EvidencePanel, EventFeedItem, AuditRow, Badge, Button } = window.EYENETDesignSystem_6752a5;

const EVIDENCE = [
  { id: 'ART-0091', ts: '12:04:51Z', indicator: '185.12.44.9', type: 'ipv4', tier: 'critical', src: 'beacon' },
  { id: 'ART-0090', ts: '12:03:18Z', indicator: 'update.svc-cdn[.]net', type: 'domain', tier: 'high', src: 'dns' },
  { id: 'ART-0088', ts: '11:59:02Z', indicator: 'a3f19e2c…b8d4', type: 'sha256', tier: 'high', src: 'file' },
  { id: 'ART-0085', ts: '11:51:40Z', indicator: 'fin-ws-04', type: 'host', tier: 'medium', src: 'edr' },
  { id: 'ART-0081', ts: '11:44:12Z', indicator: 'svc.ingest\\loader.dll', type: 'path', tier: 'medium', src: 'edr' },
  { id: 'ART-0078', ts: '11:30:55Z', indicator: 'T1071.001', type: 'ttp', tier: 'low', src: 'analyst' },
];

const SEED_FEED = [
  { id: 4, time: '12:04:51', kind: 'alert', label: 'Beacon', message: 'Outbound C2 beacon detected', source: 'fin-ws-04 → 185.12.44.9' },
  { id: 3, time: '12:04:47', kind: 'observe', label: 'DNS', message: 'Resolution for known-bad domain', source: 'update.svc-cdn[.]net' },
  { id: 2, time: '12:04:40', kind: 'info', message: 'Analyst op.krieg joined case' },
  { id: 1, time: '12:04:33', kind: 'system', label: 'Ingest', message: 'Artifact ART-0088 sealed', source: 'sha256 verified' },
];

const NEW_EVENTS = [
  { kind: 'observe', label: 'HTTP', message: 'POST to /gate.php', source: '185.12.44.9' },
  { kind: 'alert', label: 'Exfil', message: 'Anomalous outbound volume', source: 'fin-ws-04 · 42 MB' },
  { kind: 'info', label: 'Note', message: 'Correlated with CASE-2026-0402' },
  { kind: 'observe', label: 'DNS', message: 'TXT record query', source: 'c2.svc-cdn[.]net' },
];

function Panel({ title, action, children, style }) {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', minHeight: 0, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--surface)', overflow: 'hidden', ...style }}>
      <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', background: 'var(--panel)', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--text-faint)' }}>{title}</span>
        {action}
      </div>
      <div style={{ minHeight: 0, overflow: 'auto' }}>{children}</div>
    </section>
  );
}

function CaseView() {
  const [sel, setSel] = React.useState('ART-0091');
  const [feed, setFeed] = React.useState(SEED_FEED);
  const [freshId, setFreshId] = React.useState(null);
  const nid = React.useRef(5);
  const cursor = React.useRef(0);

  React.useEffect(() => {
    const t = setInterval(() => {
      const tpl = NEW_EVENTS[cursor.current % NEW_EVENTS.length];
      cursor.current += 1;
      const now = new Date();
      const time = now.toTimeString().slice(0, 8);
      const id = nid.current++;
      setFeed((f) => [{ id, time, ...tpl }, ...f].slice(0, 40));
      setFreshId(id);
      setTimeout(() => setFreshId((x) => (x === id ? null : x)), 900);
    }, 3200);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--black)' }}>
      {/* Case header */}
      <div style={{ flex: '0 0 auto', padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-faint)' }}>CASE-2026-0417</span>
          <Badge tone="critical" dot>Critical</Badge>
          <Badge tone="neutral">Active</Badge>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
          <h1 style={{ margin: 0, fontFamily: 'var(--font-sans)', fontSize: 22, fontWeight: 600, color: 'var(--text)', lineHeight: 1.2 }}>Loader campaign — EMEA finance sector</h1>
          <div style={{ display: 'flex', gap: 8, flex: '0 0 auto' }}>
            <Button variant="ghost" size="sm">Export dossier</Button>
            <Button variant="primary" size="sm">Reclassify</Button>
            <Button variant="destructive" size="sm">Seal &amp; purge</Button>
          </div>
        </div>
      </div>

      {/* Body: evidence table + right rail */}
      <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: 'minmax(0,1.7fr) minmax(320px,1fr)', gap: 16, padding: 16, overflow: 'hidden' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>
          <Panel title="Evidence — indicators & artifacts" style={{ flex: 1 }}
            action={<span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-faint)' }}>{EVIDENCE.length} items</span>}>
            <DataTable
              rowKey="id" selectedId={sel} onRowClick={(r) => setSel(r.id)}
              style={{ border: 'none', borderRadius: 0 }}
              columns={[
                { key: 'ts', header: 'Timestamp', mono: true, width: '110px' },
                { key: 'id', header: 'Artifact', mono: true, width: '96px' },
                { key: 'indicator', header: 'Indicator', mono: true },
                { key: 'type', header: 'Type', mono: true, width: '78px' },
                { key: 'tier', header: 'Tier', width: '96px', render: (v) => <Badge tone={v}>{v}</Badge> },
                { key: 'src', header: 'Source', align: 'right', width: '80px' },
              ]}
              rows={EVIDENCE}
            />
          </Panel>
          <Panel title="Audit trail — immutable" style={{ flex: '0 0 auto', maxHeight: 168 }}>
            <AuditRow time="2026-09-20 12:04:51Z" actor="op.krieg" verb="reclassified" target="ART-0091" detail="HIGH → CRITICAL" />
            <AuditRow time="2026-09-20 12:03:18Z" actor="op.krieg" verb="sealed" target="ART-0090" />
            <AuditRow time="2026-09-20 11:59:02Z" actor="svc.ingest" tamper verb="hash mismatch on" target="ART-0088" />
            <AuditRow time="2026-09-20 11:44:12Z" actor="op.krieg" verb="opened" target="CASE-2026-0417" />
          </Panel>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>
          <EvidencePanel title={`Selected — ${sel}`} style={{ flex: '0 0 auto' }}
            items={[
              { label: 'Artifact', value: sel },
              { label: 'SHA-256', value: 'a3f19e2c…b8d4' },
              { label: 'First seen', value: '2026-09-18 04:12:07Z' },
              { label: 'Classification', value: 'CRITICAL', tone: 'critical' },
              { label: 'Attributed', value: 'UNC-3312', tone: 'accent' },
              { label: 'Note', value: 'Matches known loader family', mono: false },
            ]}
          />
          <Panel title="Live event feed" style={{ flex: 1 }}
            action={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '.1em', color: 'var(--red-text)' }}><span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--red-text)' }} />STREAMING</span>}>
            {feed.map((e) => <EventFeedItem key={e.id} {...e} fresh={e.id === freshId} />)}
          </Panel>
        </div>
      </div>
    </div>
  );
}
window.CaseView = CaseView;
