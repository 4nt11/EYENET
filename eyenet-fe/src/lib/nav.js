// Primary navigation model - the API service categories grouped for the operator.
// slug matches the OpenAPI tag (contracts/openapi/eyenet.v1.yaml). href drives routing.
// `built: true` = a real screen exists; `future: true` = planned, no API yet.
// An item may carry `children` (a submenu); the parent links to its overview.

export const NAV = [
  {
    group: 'Investigate',
    items: [
      { slug: 'cases', label: 'Cases', href: '/cases', built: true, desc: 'Investigation workspace: evidence, documents, attachments, logs',
        children: [
          { slug: 'cases-overview', label: 'Overview', href: '/cases', built: true, desc: 'Case workspace and caseload' },
          { slug: 'cases-evidence', label: 'Evidence', href: '/cases/evidence', built: true, desc: 'Indicators and artifacts for the case' },
          { slug: 'documents', label: 'Documents', href: '/cases/documents', built: true, desc: 'Classified documents in the case' },
          { slug: 'attachments', label: 'Attachments', href: '/cases/attachments', built: true, desc: 'Byte-level evidence, signed access' },
          { slug: 'cases-logs', label: 'Logs', href: '/cases/logs', built: true, desc: 'Immutable, hash-chained audit for the case' },
          { slug: 'reclassify', label: 'Reclassify', href: '/cases/reclassify', built: true, desc: 'Operator-promote-only reclassification' }
        ] },
      { slug: 'actors',     label: 'Actors',     href: '/actors', built: true, desc: 'Actor detail, neighbors, observations, timeline' },
      { slug: 'personas',   label: 'Personas',   href: '/personas', built: true, desc: 'Persona detail and member list' },
      { slug: 'linkages',   label: 'Linkages',   href: '/linkages', built: true, desc: 'Linkage reads and confirm/reject/suspect decisions' },
      { slug: 'graph',      label: 'Graph',      href: '/graph', built: true, desc: 'Aggregate graph stats and actor search' },
      { slug: 'actor-groups', label: 'Actor groups', href: '/actor-groups', future: true, desc: 'Threat-actor collectives / crews (e.g. The Gentlemen, LulzSec) · no API yet' }
    ]
  },
  {
    group: 'Discovery',
    items: [
      { slug: 'sources',    label: 'Sources',    href: '/sources', built: true, desc: 'Sources & source-domains · discovery storage surface' },
      { slug: 'collectors', label: 'Collectors', href: '/collectors', built: true, desc: 'Collector fleet management' },
      { slug: 'candidates', label: 'Candidates', href: '/candidates', built: true, desc: 'GroupCandidate triage queue' },
      { slug: 'monitored-groups', label: 'Monitored groups', href: '/monitored-groups', future: true, desc: 'Chat groups we have joined / are monitoring (GroupTable) · no API yet' }
    ]
  },
  {
    group: 'Live',
    items: [
      { slug: 'stream', label: 'Live feed', href: '/stream', desc: 'Server-Sent Events · replay via Last-Event-ID' }
    ]
  },
  {
    group: 'System',
    items: [
      { slug: 'auth',       label: 'Auth & tokens', href: '/auth', built: true, desc: 'Login, refresh, PAT and stream-token minting' },
      { slug: 'identities', label: 'Identities',    href: '/identities', built: true, desc: 'Identity-pool actions · claim/release/freeze/burn' },
      { slug: 'clearance',  label: 'Clearance',     href: '/clearance', built: true, desc: 'Sensitivity-clearance grants' },
      { slug: 'control',    label: 'Control',       href: '/control', built: true, desc: 'System-wide operator actions (panic)' },
      { slug: 'health',     label: 'Health',        href: '/health', built: true, desc: 'Liveness, readiness, and Prometheus metrics' }
    ]
  }
];

// Flat slug -> item lookup (includes submenu children), for the generic placeholder.
export const BY_SLUG = Object.fromEntries(
  NAV.flatMap((g) => g.items.flatMap((i) => [[i.slug, { ...i, group: g.group }], ...(i.children ?? []).map((c) => [c.slug, { ...c, group: g.group }])]))
);
