// Mock data for the EYENET case-view mockup. No wiring · replace with API calls later.

export const CASES = [
  { caseId: 'CASE-2026-0417', title: 'Loader campaign · EMEA finance sector', tier: 'critical', tierLabel: 'Critical', actor: 'UNC-3312', openCount: 7, updated: '12:04Z' },
  { caseId: 'CASE-2026-0402', title: 'Credential harvest · supplier portal', tier: 'high', tierLabel: 'High', actor: 'UNC-2980', openCount: 3, updated: '09:51Z' },
  { caseId: 'CASE-2026-0388', title: 'Beaconing host · staging network', tier: 'medium', tierLabel: 'Medium', actor: 'unattributed', openCount: 1, updated: 'Sep 18' },
  { caseId: 'CASE-2026-0371', title: 'Phishing infra teardown', tier: 'low', tierLabel: 'Low', actor: 'UNC-2980', openCount: 0, updated: 'Sep 15' }
];

export const EVIDENCE = [
  { id: 'ART-0091', ts: '12:04:51Z', indicator: '185.12.44.9', type: 'ipv4', tier: 'critical', src: 'beacon' },
  { id: 'ART-0090', ts: '12:03:18Z', indicator: 'update.svc-cdn[.]net', type: 'domain', tier: 'high', src: 'dns' },
  { id: 'ART-0088', ts: '11:59:02Z', indicator: 'a3f19e2c…b8d4', type: 'sha256', tier: 'high', src: 'file' },
  { id: 'ART-0085', ts: '11:51:40Z', indicator: 'fin-ws-04', type: 'host', tier: 'medium', src: 'edr' },
  { id: 'ART-0081', ts: '11:44:12Z', indicator: 'svc.ingest\\loader.dll', type: 'path', tier: 'medium', src: 'edr' },
  { id: 'ART-0078', ts: '11:30:55Z', indicator: 'T1071.001', type: 'ttp', tier: 'low', src: 'analyst' }
];

export const EVIDENCE_COLUMNS = [
  { key: 'ts', header: 'Timestamp', mono: true, width: '110px' },
  { key: 'id', header: 'Artifact', mono: true, width: '96px' },
  { key: 'indicator', header: 'Indicator', mono: true },
  { key: 'type', header: 'Type', mono: true, width: '78px' },
  { key: 'tier', header: 'Tier', width: '96px', badge: true },
  { key: 'src', header: 'Source', align: 'right', width: '80px' }
];

export const SELECTED_DETAIL = (id) => [
  { label: 'Artifact', value: id },
  { label: 'SHA-256', value: 'a3f19e2c…b8d4' },
  { label: 'First seen', value: '2026-09-18 04:12:07Z' },
  { label: 'Classification', value: 'CRITICAL', tone: 'critical' },
  { label: 'Attributed', value: 'UNC-3312', tone: 'accent' },
  { label: 'Note', value: 'Matches known loader family', mono: false }
];

export const AUDIT = [
  { time: '2026-09-20 12:04:51Z', actor: 'op.krieg', verb: 'reclassified', target: 'ART-0091', detail: 'HIGH → CRITICAL' },
  { time: '2026-09-20 12:03:18Z', actor: 'op.krieg', verb: 'sealed', target: 'ART-0090' },
  { time: '2026-09-20 11:59:02Z', actor: 'svc.ingest', verb: 'hash mismatch on', target: 'ART-0088', tamper: true },
  { time: '2026-09-20 11:44:12Z', actor: 'op.krieg', verb: 'opened', target: 'CASE-2026-0417' }
];

export const SEED_FEED = [
  { id: 4, time: '12:04:51', kind: 'alert', label: 'Beacon', message: 'Outbound C2 beacon detected', source: 'fin-ws-04 → 185.12.44.9' },
  { id: 3, time: '12:04:47', kind: 'observe', label: 'DNS', message: 'Resolution for known-bad domain', source: 'update.svc-cdn[.]net' },
  { id: 2, time: '12:04:40', kind: 'info', message: 'Analyst op.krieg joined case' },
  { id: 1, time: '12:04:33', kind: 'system', label: 'Ingest', message: 'Artifact ART-0088 sealed', source: 'sha256 verified' }
];

export const NEW_EVENTS = [
  { kind: 'observe', label: 'HTTP', message: 'POST to /gate.php', source: '185.12.44.9' },
  { kind: 'alert', label: 'Exfil', message: 'Anomalous outbound volume', source: 'fin-ws-04 · 42 MB' },
  { kind: 'info', label: 'Note', message: 'Correlated with CASE-2026-0402' },
  { kind: 'observe', label: 'DNS', message: 'TXT record query', source: 'c2.svc-cdn[.]net' }
];

// ── Clearance ──────────────────────────────────────────────────────────────
export const CLEARANCE_GRANTS = [
  { id: 'GRANT-0042', user: 'op.krieg',  scope: 'read:restricted', tier: 'critical', status: 'active',  grantedBy: 'op.admin', expires: '2026-10-04 00:00Z' },
  { id: 'GRANT-0041', user: 'op.vega',   scope: 'read:restricted', tier: 'high',     status: 'active',  grantedBy: 'op.admin', expires: '2026-09-28 00:00Z' },
  { id: 'GRANT-0039', user: 'op.krieg',  scope: 'admin:reclassify', tier: 'critical', status: 'active', grantedBy: 'op.admin', expires: '2026-09-24 12:00Z' },
  { id: 'GRANT-0037', user: 'op.reyes',  scope: 'read:restricted', tier: 'medium',   status: 'expired', grantedBy: 'op.admin', expires: '2026-09-19 00:00Z' },
  { id: 'GRANT-0033', user: 'svc.export', scope: 'read:restricted', tier: 'high',    status: 'revoked', grantedBy: 'op.admin', expires: '2026-09-30 00:00Z' }
];

export const CLEARANCE_COLUMNS = [
  { key: 'id', header: 'Grant', mono: true, width: '110px' },
  { key: 'user', header: 'User', mono: true, width: '110px' },
  { key: 'scope', header: 'Scope', mono: true },
  { key: 'tier', header: 'Sensitivity', width: '110px', badge: true },
  { key: 'grantedBy', header: 'Granted by', mono: true, width: '110px' },
  { key: 'expires', header: 'Expires', mono: true, width: '170px' },
  { key: 'status', header: 'Status', align: 'right', width: '90px' }
];

// ── Audit ──────────────────────────────────────────────────────────────────
export const AUDIT_VERIFY = { verified: true, entries: 18432, lastAnchor: 'sha256:9f2c…4e1a', anchoredAt: '2026-09-20 00:00:00Z' };

export const AUDIT_LOG = [
  { time: '2026-09-20 12:04:51Z', actor: 'op.krieg',   verb: 'reclassified', target: 'ART-0091', detail: 'HIGH → CRITICAL' },
  { time: '2026-09-20 12:03:18Z', actor: 'op.krieg',   verb: 'sealed', target: 'ART-0090' },
  { time: '2026-09-20 11:59:02Z', actor: 'svc.ingest', verb: 'hash mismatch on', target: 'ART-0088', tamper: true },
  { time: '2026-09-20 11:57:40Z', actor: 'op.vega',    verb: 'accessed', target: 'blob:7c1e…', detail: 'file-access, signed' },
  { time: '2026-09-20 11:44:12Z', actor: 'op.krieg',   verb: 'opened', target: 'CASE-2026-0417' },
  { time: '2026-09-20 11:30:55Z', actor: 'op.krieg',   verb: 'granted', target: 'GRANT-0042', detail: 'read:restricted → op.krieg' },
  { time: '2026-09-20 10:12:03Z', actor: 'svc.discovery', verb: 'promoted', target: 'GC-2211', detail: 'candidate → source' },
  { time: '2026-09-20 09:51:47Z', actor: 'op.vega',    verb: 'confirmed', target: 'LNK-0087', detail: 'linkage: UNC-3312 ↔ UNC-2980' },
  { time: '2026-09-20 09:03:22Z', actor: 'op.admin',   verb: 'revoked', target: 'GRANT-0033', detail: 'svc.export' },
  { time: '2026-09-20 08:40:10Z', actor: 'svc.classifier', verb: 'classified', target: 'DOC-0455', detail: 'RESTRICTED' },
  { time: '2026-09-20 08:15:00Z', actor: 'svc.collector', verb: 'joined', target: 'GRP-9981', detail: 'telegram' },
  { time: '2026-09-20 00:00:00Z', actor: 'svc.audit',  verb: 'anchored', target: 'seq:18400', detail: 'external anchor written' }
];

export const AUDIT_ANCHORS = [
  { seq: 18400, hash: 'sha256:9f2c…4e1a', anchoredAt: '2026-09-20 00:00:00Z', target: 'ots+btc' },
  { seq: 17920, hash: 'sha256:1b83…c07d', anchoredAt: '2026-09-19 00:00:00Z', target: 'ots+btc' },
  { seq: 17440, hash: 'sha256:aa41…9f22', anchoredAt: '2026-09-18 00:00:00Z', target: 'ots+btc' }
];

export const ANCHOR_COLUMNS = [
  { key: 'seq', header: 'Seq', mono: true, width: '90px' },
  { key: 'hash', header: 'Chain hash', mono: true },
  { key: 'target', header: 'Anchor', mono: true, width: '110px' },
  { key: 'anchoredAt', header: 'Anchored', mono: true, align: 'right', width: '180px' }
];

// ── Health / system ──────────────────────────────────────────────────────────
// status: 'ready' (calm/neutral) | 'degraded' (accent) | 'down' (red)
export const HEALTH = {
  ready: true,
  liveness: 'ok',
  components: [
    { name: 'storage.main',  status: 'ready',    detail: 'aiosqlite · 3.1 GB · ping 0.4 ms' },
    { name: 'storage.audit', status: 'ready',    detail: 'chain verified · seq 18432' },
    { name: 'bus',           status: 'ready',    detail: 'NATS · connected · 4 subjects' },
    { name: 'collectors',    status: 'degraded', detail: '2/3 running · matrix-01 reconnecting' },
    { name: 'classifier',    status: 'ready',    detail: 'jail canary ok · queue 0' },
    { name: 'discovery',     status: 'ready',    detail: 'scout idle · 1 candidate pending' }
  ]
};

export const SYS_STATS = [
  { label: 'Uptime',       value: '14d 06:12', tone: 'default' },
  { label: 'Events / sec', value: '182',       tone: 'default', sub: 'peak 640' },
  { label: 'Ingest queue', value: '0',         tone: 'default', sub: 'no backlog' },
  { label: 'Memory',       value: '412', unit: 'MB', tone: 'default', sub: 'rss · 6% of host' },
  { label: 'Open cases',   value: '4',         tone: 'accent' },
  { label: 'Active alerts', value: '1',        tone: 'critical', sub: 'beacon · CASE-0417' }
];

// Graph mocks removed — /graph is wired to GET /v1/graph/stats + /v1/graph/search.

// ── Sources (discovery storage surface) ──────────────────────────────────────
// state: active | paused
const SOURCE_TONE = { active: 'neutral', paused: 'low' };
export const sourceTone = (s) => SOURCE_TONE[s] ?? 'neutral';

export const SOURCES = [
  { id: 'SRC-0007', platform: 'telegram', name: 'loader-ops',       state: 'active', domainCount: 3, lastIngest: '2026-09-20 12:04Z',
    domains: ['loader-ops', 'loader-ops-2', 'svc-cdn[.]net'] },
  { id: 'SRC-0012', platform: 'matrix',   name: '#staging:svc-cdn', state: 'active', domainCount: 1, lastIngest: '2026-09-20 11:58Z',
    domains: ['svc-cdn.net'] },
  { id: 'SRC-0005', platform: 'telegram', name: 'fin-sector-chat',  state: 'active', domainCount: 2, lastIngest: '2026-09-20 09:12Z',
    domains: ['fin-sector-chat', 'supplier-portal'] },
  { id: 'SRC-0003', platform: 'telegram', name: 'phishing-infra',   state: 'paused', domainCount: 0, lastIngest: '2026-09-15 17:40Z',
    domains: [] }
];

export const SOURCE_COLUMNS = [
  { key: 'id', header: 'Source', mono: true, width: '96px' },
  { key: 'platform', header: 'Platform', mono: true, width: '90px' },
  { key: 'name', header: 'Name', mono: true },
  { key: 'state', header: 'State', badge: true, tone: sourceTone, width: '96px' },
  { key: 'domainCount', header: 'Domains', mono: true, align: 'right', width: '90px' },
  { key: 'lastIngest', header: 'Last ingest', mono: true, align: 'right', width: '160px' }
];

// ── Collectors (fleet) ───────────────────────────────────────────────────────
// state: running | degraded | stopped
const COLLECTOR_TONE = { running: 'neutral', degraded: 'high', stopped: 'low' };
export const collectorTone = (s) => COLLECTOR_TONE[s] ?? 'neutral';

export const COLLECTORS = [
  { id: 'tg-collector-01', kind: 'telegram', state: 'running',  identity: 'ID-0071', memberships: 12, heartbeat: '2026-09-20 12:04:48Z' },
  { id: 'tg-collector-02', kind: 'telegram', state: 'running',  identity: 'ID-0069', memberships: 8,  heartbeat: '2026-09-20 12:04:46Z' },
  { id: 'mx-collector-01', kind: 'matrix',   state: 'degraded', identity: 'ID-0055', memberships: 4,  heartbeat: '2026-09-20 12:01:11Z' },
  { id: 'tg-collector-03', kind: 'telegram', state: 'stopped',  identity: '·',       memberships: 0,  heartbeat: '2026-09-19 22:30:02Z' }
];

export const COLLECTOR_COLUMNS = [
  { key: 'id', header: 'Collector', mono: true, width: '150px' },
  { key: 'kind', header: 'Kind', mono: true, width: '90px' },
  { key: 'state', header: 'State', badge: true, tone: collectorTone, width: '110px' },
  { key: 'identity', header: 'Identity', mono: true, width: '96px' },
  { key: 'memberships', header: 'Groups', mono: true, align: 'right', width: '80px' },
  { key: 'heartbeat', header: 'Heartbeat', mono: true, align: 'right', width: '180px' }
];

// ── Actors (threat-actor dossiers + BEHAVE engine readout) ───────────────────
// Field names mirror the backend: ActorDetail, ObservationSummary (kind =
// "namespace:name"), NeighborEdge, the four Linker simhash comparators, and the
// Verifier (NCD = compression_distance, GI = general_impostors). Language is the
// ISO 639-1 code carried in Observation.source (#es / #en), NOT a BCP-47 xx-YY.
export const THREAT_LABEL = { critical: 'Severe', high: 'Elevated', medium: 'Moderate', low: 'Guarded' };

export const ACTORS = [
  {
    actor_id: 'ACT-3312', primary_handle: 'krieg_wolf', platforms: ['telegram'], score: 0.94,
    tier: 'critical', language: 'es',
    first_seen: '2026-07-02 08:14:00Z', last_seen: '2026-09-20 12:04:51Z',
    alias_count: 3, observation_count: 214, persona_id: 'PER-0044',
    aliases: ['krieg_wolf', 'k.wolf', 'loader_admin'],
    groups: [{ id: 'GRP-9981', name: 'loader-ops', platform: 'telegram' }],
    assessment: 'Hands-on-keyboard operator of the EMEA loader campaign. Active C2, high operational tempo, admin of loader-ops.',
    recipe: { name: 'chatty_member', version: '0.1', confidence: 0.9, basis: 'msg_count 214 ≥ 195' },
    role_signal: 'group_admin',
    behave: {
      language: 'es', anchors: 6, dialect_region: 'es regional markers (#dialect-markers-v1)',
      activity: [
        { primitive: 'meta.total_messages', version: '0.1', kind: 'numeric', label: 'Total messages', value: '214' },
        { primitive: 'meta.msg_per_day', version: '0.1', kind: 'numeric', label: 'Messages / day', value: '9.3' },
        { primitive: 'meta.active_days', version: '0.1', kind: 'numeric', label: 'Active days', value: '62' },
        { primitive: 'meta.activity_density', version: '0.1', kind: 'numeric', label: 'Activity density', value: '0.78' },
        { primitive: 'meta.fingerprint_confidence', version: '0.1', kind: 'numeric', label: 'Fingerprint confidence', value: '0.91' }
      ],
      lexical: [
        { primitive: 'lexical.vocabulary_richness', version: '0.2', kind: 'numeric', label: 'MATTR (vocabulary richness)', value: '0.41' },
        { primitive: 'lexical.evaluative_morphology_density', version: '0.1', kind: 'numeric', label: 'Evaluative morphology density', value: '0.12' },
        { primitive: 'lexical.dialect_region', version: '0.1', kind: 'array_str', label: 'Dialect region markers', value: 'top-rate 0.006' }
      ],
      stylometric: [
        { primitive: 'stylometric.function_word_distribution_top50', version: '0.2', kind: 'hash', label: 'Function-word top-50 simhash', value: 'a91f…#es' },
        { primitive: 'stylometric.punctuation_style', version: '0.1', kind: 'hash', label: 'Punctuation style (13-token)', value: 'c40d…' },
        { primitive: 'stylometric.message_length_variance_class', version: '0.1', kind: 'enum_str', label: 'Msg-length variance class', value: 'low_variance' },
        { primitive: 'stylometric.pos_ngram_signature', version: '0.1', kind: 'hash', label: 'POS-bigram simhash', value: '77b2…#es' }
      ],
      comparators: [
        { name: 'function_word_simhash_hamming', status: 'disabled', threshold: null, reason: 'ES precision floor (M5 Rutify)' },
        { name: 'char_ngram_simhash_hamming', status: 'disabled', threshold: null, reason: 'ES precision floor (M5 Rutify)' },
        { name: 'pos_ngram_simhash_hamming', status: 'disabled', threshold: null, reason: 'ES precision floor (M6.5, AUC 0.61)' },
        { name: 'optional_grammar_simhash_hamming', status: 'disabled', threshold: null, reason: 'ES precision floor (M6.5, AUC 0.63)' }
      ],
      verifier: {
        composite: 0.83, floor: 0.70, state: 'SUSPECTED',
        results: [
          { verifier: 'compression_distance', score: 0.81, confidence: 1.0, skipped: false, detail: 'NCD 0.19 · zlib-6' },
          { verifier: 'general_impostors', score: 0.86, confidence: 1.0, skipped: false, detail: 'wins 43/50 · pool 40' }
        ]
      }
    },
    observations: [
      { observation_id: 'OBS-9912', kind: 'stylometric:function_word_distribution_top50', ts: '2026-09-20 12:00Z', score: null, sensitivity: 'NORMAL' },
      { observation_id: 'OBS-9908', kind: 'lexical:vocabulary_richness', ts: '2026-09-20 11:40Z', score: 0.41, sensitivity: 'NORMAL' },
      { observation_id: 'OBS-9901', kind: 'meta:msg_per_day', ts: '2026-09-20 11:20Z', score: 9.3, sensitivity: 'NORMAL' },
      { observation_id: 'OBS-9887', kind: 'interaction:conversation_initiation_rate', ts: '2026-09-20 10:55Z', score: 0.34, sensitivity: 'NORMAL' }
    ],
    neighbors: [
      { edge_type: 'belongs_to_persona', target_id: 'PER-0044', since: '2026-08-01', via_linkage_id: 'LNK-0087' },
      { edge_type: 'linked_to', target_id: 'ACT-2980', state: 'confirmed', method: 'verifier_composite', score: 0.86, linkage_id: 'LNK-0087' },
      { edge_type: 'linked_to', target_id: 'ACT-1774', state: 'suspected', method: 'compression_distance', score: 0.72, linkage_id: 'LNK-0104' }
    ],
    timeline: [
      { ts: '2026-09-20 12:04Z', kind: 'message', summary: 'gate listo, subiendo el loader ahora' },
      { ts: '2026-09-20 12:00Z', kind: 'observation', summary: 'stylometric:function_word_distribution_top50' },
      { ts: '2026-09-20 11:38Z', kind: 'message', summary: 'nadie toca el panel hasta que yo diga' }
    ]
  },
  {
    actor_id: 'ACT-2980', primary_handle: 'silent_relay', platforms: ['telegram', 'matrix'], score: 0.81,
    tier: 'high', language: 'en',
    first_seen: '2026-06-18 21:02:00Z', last_seen: '2026-09-20 09:51:00Z',
    alias_count: 2, observation_count: 141, persona_id: 'PER-0031',
    aliases: ['silent_relay', 's.relay'],
    groups: [
      { id: 'GRP-9981', name: 'loader-ops', platform: 'telegram' },
      { id: 'GRP-9970', name: '#staging:svc-cdn', platform: 'matrix' }
    ],
    assessment: 'Infrastructure relay and credential broker across the supplier-portal harvest. Cross-platform, disciplined OPSEC.',
    recipe: { name: 'chatty_member', version: '0.1', confidence: 0.71, basis: 'msg_count 141 < 195 (below floor)' },
    role_signal: 'credential_broker',
    behave: {
      language: 'en', anchors: 5, dialect_region: 'no strong regional markers',
      activity: [
        { primitive: 'meta.total_messages', version: '0.1', kind: 'numeric', label: 'Total messages', value: '141' },
        { primitive: 'meta.msg_per_day', version: '0.1', kind: 'numeric', label: 'Messages / day', value: '3.1' },
        { primitive: 'meta.active_days', version: '0.1', kind: 'numeric', label: 'Active days', value: '62' },
        { primitive: 'meta.activity_density', version: '0.1', kind: 'numeric', label: 'Activity density', value: '0.44' },
        { primitive: 'meta.fingerprint_confidence', version: '0.1', kind: 'numeric', label: 'Fingerprint confidence', value: '0.84' }
      ],
      lexical: [
        { primitive: 'lexical.vocabulary_richness', version: '0.2', kind: 'numeric', label: 'MATTR (vocabulary richness)', value: '0.52' }
      ],
      stylometric: [
        { primitive: 'stylometric.function_word_distribution_top50', version: '0.2', kind: 'hash', label: 'Function-word top-50 simhash', value: 'b12c…#en' },
        { primitive: 'stylometric.character_ngram_simhash', version: '0.2', kind: 'hash', label: 'Character n-gram simhash', value: 'e5a0…' },
        { primitive: 'stylometric.typo_signature', version: '0.1', kind: 'hash', label: 'Persistent-typo signature', value: '1f9d…' }
      ],
      comparators: [
        { name: 'function_word_simhash_hamming', status: 'active', threshold: 8, distance: 3, match: true },
        { name: 'char_ngram_simhash_hamming', status: 'active', threshold: 10, distance: 6, match: true },
        { name: 'pos_ngram_simhash_hamming', status: 'active', threshold: 10, distance: 11, match: false },
        { name: 'optional_grammar_simhash_hamming', status: 'active', threshold: 12, distance: 9, match: true }
      ],
      verifier: {
        composite: 0.77, floor: 0.70, state: 'SUSPECTED',
        results: [
          { verifier: 'compression_distance', score: 0.74, confidence: 1.0, skipped: false, detail: 'NCD 0.26 · zlib-6' },
          { verifier: 'general_impostors', score: 0.80, confidence: 1.0, skipped: false, detail: 'wins 40/50 · pool 40' }
        ]
      }
    },
    observations: [
      { observation_id: 'OBS-8801', kind: 'stylometric:character_ngram_simhash', ts: '2026-09-20 09:50Z', score: null, sensitivity: 'NORMAL' },
      { observation_id: 'OBS-8790', kind: 'stylometric:typo_signature', ts: '2026-09-20 09:12Z', score: null, sensitivity: 'NORMAL' },
      { observation_id: 'OBS-8777', kind: 'meta:active_days', ts: '2026-09-19 23:00Z', score: 62, sensitivity: 'NORMAL' }
    ],
    neighbors: [
      { edge_type: 'belongs_to_persona', target_id: 'PER-0031', since: '2026-07-10', via_linkage_id: 'LNK-0088' },
      { edge_type: 'linked_to', target_id: 'ACT-3312', state: 'confirmed', method: 'verifier_composite', score: 0.86, linkage_id: 'LNK-0087' }
    ],
    timeline: [
      { ts: '2026-09-20 09:51Z', kind: 'message', summary: 'fresh combos in the usual place, dm for price' },
      { ts: '2026-09-20 09:12Z', kind: 'observation', summary: 'stylometric:typo_signature' }
    ]
  },
  {
    actor_id: 'ACT-1774', primary_handle: 'ghostpost', platforms: ['telegram'], score: 0.33,
    tier: 'low', language: 'en',
    first_seen: '2026-08-30 03:11:00Z', last_seen: '2026-09-19 04:20:00Z',
    alias_count: 1, observation_count: 33, persona_id: null,
    aliases: ['ghostpost'],
    groups: [{ id: 'GRP-9958', name: 'random-memes-88', platform: 'telegram' }],
    assessment: 'Peripheral lurker. Low posting volume, rarely initiates. No confirmed attribution.',
    recipe: { name: 'lurker_or_observer', version: '0.3', confidence: 0.82, basis: 'init_rate 0.08 ≤ 0.20 (Pattern A)' },
    role_signal: 'lurker_or_observer',
    behave: {
      language: 'en', anchors: 3, dialect_region: 'insufficient corpus',
      activity: [
        { primitive: 'meta.total_messages', version: '0.1', kind: 'numeric', label: 'Total messages', value: '33' },
        { primitive: 'meta.msg_per_day', version: '0.1', kind: 'numeric', label: 'Messages / day', value: '1.6' },
        { primitive: 'meta.active_days', version: '0.1', kind: 'numeric', label: 'Active days', value: '12' },
        { primitive: 'meta.activity_density', version: '0.1', kind: 'numeric', label: 'Activity density', value: '0.11' },
        { primitive: 'meta.fingerprint_confidence', version: '0.1', kind: 'numeric', label: 'Fingerprint confidence', value: '0.41' }
      ],
      lexical: [
        { primitive: 'lexical.vocabulary_richness', version: '0.2', kind: 'numeric', label: 'MATTR (vocabulary richness)', value: '0.61' }
      ],
      stylometric: [
        { primitive: 'stylometric.message_length_class', version: '0.1', kind: 'enum_str', label: 'Msg-length class', value: 'short' }
      ],
      comparators: [
        { name: 'function_word_simhash_hamming', status: 'active', threshold: 8, distance: null, match: null, reason: 'corpus below min for stable simhash' },
        { name: 'char_ngram_simhash_hamming', status: 'active', threshold: 10, distance: null, match: null, reason: 'corpus below min for stable simhash' }
      ],
      verifier: {
        composite: null, floor: 0.70, state: 'skipped',
        results: [
          { verifier: 'compression_distance', score: 0.0, confidence: 0.0, skipped: true, detail: 'too_few_messages (< 10)' },
          { verifier: 'general_impostors', score: 0.0, confidence: 0.0, skipped: true, detail: 'too_few_messages (< 30)' }
        ]
      }
    },
    observations: [
      { observation_id: 'OBS-7010', kind: 'meta:total_messages', ts: '2026-09-19 04:20Z', score: 33, sensitivity: 'NORMAL' },
      { observation_id: 'OBS-7002', kind: 'interaction:conversation_initiation_rate', ts: '2026-09-18 22:00Z', score: 0.08, sensitivity: 'NORMAL' }
    ],
    neighbors: [
      { edge_type: 'linked_to', target_id: 'ACT-3312', state: 'suspected', method: 'compression_distance', score: 0.72, linkage_id: 'LNK-0104' }
    ],
    timeline: [
      { ts: '2026-09-19 04:20Z', kind: 'message', summary: 'lol' }
    ]
  }
];

export const ACTOR_OBS_COLUMNS = [
  { key: 'ts', header: 'Timestamp', mono: true, width: '150px' },
  { key: 'kind', header: 'Primitive (namespace:name)', mono: true },
  { key: 'score', header: 'Score', mono: true, align: 'right', width: '80px' },
  { key: 'sensitivity', header: 'Sensitivity', mono: true, align: 'right', width: '110px' }
];

// ── Personas (attribution clusters) ──────────────────────────────────────────
export const PERSONAS = [
  {
    persona_id: 'PER-0044', label: 'UNC-3312', member_count: 3, tier: 'critical',
    created_at: '2026-08-01 06:00:00Z', updated_at: '2026-09-20 12:05:00Z',
    summary: 'Attributed persona behind the EMEA loader campaign. Spans two collection sources; attribution driven by the Verifier since all four simhashes are disabled for Spanish.',
    members: [
      { actor_id: 'ACT-3312', primary_handle: 'krieg_wolf', tier: 'critical', since: '2026-08-01', via_linkage_id: 'LNK-0087' },
      { actor_id: 'ACT-2980', primary_handle: 'silent_relay', tier: 'high', since: '2026-08-04', via_linkage_id: 'LNK-0087' },
      { actor_id: 'ACT-4120', primary_handle: 'panel_hands', tier: 'high', since: '2026-09-02', via_linkage_id: 'LNK-0091' }
    ],
    linkages: [
      { linkage_id: 'LNK-0087', actor_a_id: 'ACT-3312', actor_b_id: 'ACT-2980', state: 'confirmed', method: 'verifier_composite', score: 0.86,
        evidence: [
          { comparator: 'compression_distance', score: 0.81, detail: 'NCD 0.19' },
          { comparator: 'general_impostors', score: 0.86, detail: 'wins 43/50 · pool 40' }
        ] },
      { linkage_id: 'LNK-0091', actor_a_id: 'ACT-3312', actor_b_id: 'ACT-4120', state: 'confirmed', method: 'general_impostors', score: 0.79,
        evidence: [ { comparator: 'general_impostors', score: 0.79, detail: 'wins 39/50 · pool 40' } ] }
    ]
  },
  {
    persona_id: 'PER-0031', label: 'UNC-2980', member_count: 2, tier: 'high',
    created_at: '2026-07-10 14:22:00Z', updated_at: '2026-09-20 09:52:00Z',
    summary: 'Credential-broker persona operating across the supplier-portal harvest. English-language; attribution corroborated by active simhash comparators plus the Verifier.',
    members: [
      { actor_id: 'ACT-2980', primary_handle: 'silent_relay', tier: 'high', since: '2026-07-10', via_linkage_id: 'LNK-0088' },
      { actor_id: 'ACT-3901', primary_handle: 'combo_vend', tier: 'medium', since: '2026-08-20', via_linkage_id: 'LNK-0093' }
    ],
    linkages: [
      { linkage_id: 'LNK-0088', actor_a_id: 'ACT-2980', actor_b_id: 'ACT-3901', state: 'confirmed', method: 'function_word_simhash_hamming', score: 0.83,
        evidence: [
          { comparator: 'function_word_simhash_hamming', score: 0.88, detail: 'hamming 3 ≤ 8' },
          { comparator: 'compression_distance', score: 0.74, detail: 'NCD 0.26' }
        ] }
    ]
  },
  {
    persona_id: 'PER-0019', label: 'UNC-2201', member_count: 1, tier: 'low',
    created_at: '2026-05-30 10:00:00Z', updated_at: '2026-09-10 08:00:00Z',
    summary: 'Single-actor persona, retained for the phishing-infra teardown. No further members attributed.',
    members: [
      { actor_id: 'ACT-2201', primary_handle: 'mailer_x', tier: 'low', since: '2026-05-30', via_linkage_id: null }
    ],
    linkages: []
  }
];

// ── Linkages (attribution decisions) ─────────────────────────────────────────
// LinkageState: proposed | suspected | confirmed | rejected | superseded.
// Persona aggregation fires ONLY on transition into confirmed.
const LINKAGE_TONE = { proposed: 'medium', suspected: 'high', confirmed: 'neutral', rejected: 'low', superseded: 'low' };
export const linkageTone = (s) => LINKAGE_TONE[s] ?? 'neutral';

export const LINKAGES = [
  {
    linkage_id: 'LNK-0087', pair: 'krieg_wolf ↔ silent_relay',
    actor_a: { id: 'ACT-3312', handle: 'krieg_wolf', tier: 'critical' },
    actor_b: { id: 'ACT-2980', handle: 'silent_relay', tier: 'high' },
    state: 'confirmed', method: 'verifier_composite', score: 0.86,
    proposed_at: '2026-08-03 22:10Z', decided_at: '2026-08-04 07:41Z', decided_by: 'op.krieg',
    evidence: [
      { comparator: 'compression_distance', score: 0.81, detail: 'NCD 0.19 · zlib-6' },
      { comparator: 'general_impostors', score: 0.86, detail: 'wins 43/50 · pool 40' }
    ]
  },
  {
    linkage_id: 'LNK-0104', pair: 'krieg_wolf ↔ ghostpost',
    actor_a: { id: 'ACT-3312', handle: 'krieg_wolf', tier: 'critical' },
    actor_b: { id: 'ACT-1774', handle: 'ghostpost', tier: 'low' },
    state: 'suspected', method: 'compression_distance', score: 0.72,
    proposed_at: '2026-09-19 05:02Z', decided_at: null, decided_by: null,
    evidence: [
      { comparator: 'compression_distance', score: 0.72, detail: 'NCD 0.28 · zlib-6' }
    ]
  },
  {
    linkage_id: 'LNK-0120', pair: 'panel_hands ↔ krieg_wolf',
    actor_a: { id: 'ACT-4120', handle: 'panel_hands', tier: 'high' },
    actor_b: { id: 'ACT-3312', handle: 'krieg_wolf', tier: 'critical' },
    state: 'proposed', method: 'general_impostors', score: 0.79,
    proposed_at: '2026-09-02 11:20Z', decided_at: null, decided_by: null,
    evidence: [
      { comparator: 'general_impostors', score: 0.79, detail: 'wins 39/50 · pool 40' }
    ]
  },
  {
    linkage_id: 'LNK-0088', pair: 'silent_relay ↔ combo_vend',
    actor_a: { id: 'ACT-2980', handle: 'silent_relay', tier: 'high' },
    actor_b: { id: 'ACT-3901', handle: 'combo_vend', tier: 'medium' },
    state: 'confirmed', method: 'function_word_simhash_hamming', score: 0.83,
    proposed_at: '2026-07-09 18:33Z', decided_at: '2026-07-10 09:15Z', decided_by: 'op.vega',
    evidence: [
      { comparator: 'function_word_simhash_hamming', score: 0.88, detail: 'hamming 3 ≤ 8 (en)' },
      { comparator: 'compression_distance', score: 0.74, detail: 'NCD 0.26 · zlib-6' }
    ]
  },
  {
    linkage_id: 'LNK-0119', pair: 'combo_vend ↔ mailer_x',
    actor_a: { id: 'ACT-3901', handle: 'combo_vend', tier: 'medium' },
    actor_b: { id: 'ACT-2201', handle: 'mailer_x', tier: 'low' },
    state: 'rejected', method: 'general_impostors', score: 0.41,
    proposed_at: '2026-09-05 14:00Z', decided_at: '2026-09-05 16:22Z', decided_by: 'op.vega',
    evidence: [
      { comparator: 'general_impostors', score: 0.41, detail: 'wins 20/50 · below floor' }
    ]
  }
];

export const LINKAGE_COLUMNS = [
  { key: 'linkage_id', header: 'Linkage', mono: true, width: '96px' },
  { key: 'pair', header: 'Actor pair', mono: true },
  { key: 'state', header: 'State', badge: true, tone: linkageTone, width: '110px' },
  { key: 'method', header: 'Method', mono: true, width: '190px' },
  { key: 'score', header: 'Score', mono: true, align: 'right', width: '80px' }
];

// ── Auth & tokens (operator session surface) ─────────────────────────────────
export const SESSION = {
  user: 'op.krieg', role: 'analyst', mfa: 'enabled', session_expires: '2026-09-20 16:04Z',
  scopes: ['read:actors', 'read:observations', 'read:graph', 'read:cases', 'write:cases',
    'write:linkage_decision', 'write:persona_decision', 'read:metrics']
};

export const PATS = [
  { id: 'PAT-0007', label: 'prometheus-scrape', scopes: 'read:metrics', last_used: '2026-09-20 12:00Z', expires: '2026-12-01', status: 'active' },
  { id: 'PAT-0005', label: 'ci-export', scopes: 'read:cases', last_used: '2026-09-18 04:11Z', expires: '2026-10-12', status: 'active' },
  { id: 'PAT-0003', label: 'old-laptop', scopes: 'read:actors read:graph', last_used: '2026-07-30 22:40Z', expires: '2026-09-01', status: 'expired' }
];
export const PAT_COLUMNS = [
  { key: 'id', header: 'Token', mono: true, width: '96px' },
  { key: 'label', header: 'Label', mono: true, width: '160px' },
  { key: 'scopes', header: 'Scopes', mono: true },
  { key: 'last_used', header: 'Last used', mono: true, align: 'right', width: '160px' },
  { key: 'status', header: 'Status', mono: true, align: 'right', width: '90px' }
];

export const SIGNING_KEYS = [
  { id: 'KEY-0002', algo: 'ed25519', fingerprint: 'SHA256:9f2c…4e1a', added: '2026-08-20', status: 'active' },
  { id: 'KEY-0001', algo: 'ed25519', fingerprint: 'SHA256:1b83…c07d', added: '2026-05-10', status: 'active' }
];
export const KEY_COLUMNS = [
  { key: 'id', header: 'Key', mono: true, width: '96px' },
  { key: 'algo', header: 'Algo', mono: true, width: '90px' },
  { key: 'fingerprint', header: 'Fingerprint', mono: true },
  { key: 'added', header: 'Added', mono: true, align: 'right', width: '120px' },
  { key: 'status', header: 'Status', mono: true, align: 'right', width: '90px' }
];

// ── Control (system-wide operator actions) ───────────────────────────────────
export const PANIC = {
  posture: 'normal', // normal | armed | tripped
  effects: [
    'Stop every collector in the fleet immediately',
    'Freeze the entire identity pool',
    'Halt ingest and seal open evidence',
    'Emit a signed control-plane panic event to the audit chain'
  ]
};
export const CONTROL_LOG = [
  { time: '2026-09-14 03:00:00Z', actor: 'op.admin', verb: 'ran panic drill', target: 'control', detail: 'dry-run, no effects applied' },
  { time: '2026-08-01 12:00:00Z', actor: 'op.admin', verb: 'rotated', target: 'panic authorizer key', detail: 'scheduled rotation' }
];

// ── Monitored groups (FUTURE · no API yet) ───────────────────────────────────
// Chat channels we have joined / are surveilling. Backed by GroupTable in the
// model layer, but no /v1/groups route exists yet. Mock for design review.
const MGROUP_TONE = { monitored: 'neutral', parked: 'low', left: 'low' };
export const mgroupTone = (s) => MGROUP_TONE[s] ?? 'neutral';

export const MONITORED_GROUPS = [
  { id: 'GRP-9981', name: 'loader-ops', platform: 'telegram', source_id: 'SRC-0007', members: 214, messages: 18402,
    last_activity: '2026-09-20 12:04Z', state: 'monitored', collector: 'tg-collector-01', seed_root: true,
    actors_seen: ['krieg_wolf', 'silent_relay', 'panel_hands'] },
  { id: 'GRP-9970', name: '#staging:svc-cdn', platform: 'matrix', source_id: 'SRC-0012', members: 38, messages: 2201,
    last_activity: '2026-09-20 11:58Z', state: 'monitored', collector: 'mx-collector-01', seed_root: false,
    actors_seen: ['silent_relay'] },
  { id: 'GRP-9958', name: 'random-memes-88', platform: 'telegram', source_id: null, members: 1200, messages: 88213,
    last_activity: '2026-09-19 04:20Z', state: 'parked', collector: null, seed_root: false,
    actors_seen: ['ghostpost'] }
];
export const MGROUP_COLUMNS = [
  { key: 'id', header: 'Group', mono: true, width: '96px' },
  { key: 'name', header: 'Name', mono: true },
  { key: 'platform', header: 'Platform', mono: true, width: '90px' },
  { key: 'state', header: 'State', badge: true, tone: mgroupTone, width: '100px' },
  { key: 'members', header: 'Members', mono: true, align: 'right', width: '90px' },
  { key: 'last_activity', header: 'Last activity', mono: true, align: 'right', width: '160px' }
];

// ── Actor groups / crews (FUTURE · no model, no API) ─────────────────────────
// Threat-actor collectives (The Gentlemen, LulzSec). Not in the codebase at all;
// this is a pure design proposal for a future engine + API surface.
export const ACTOR_GROUPS = [
  { id: 'CREW-002', name: 'The Gentlemen', tier: 'critical', aka: ['TG', 'gentlemen-crew'],
    first_seen: '2026-05', assessment: 'Financially-motivated loader crew operating against EMEA finance. Disciplined OPSEC, tiered roles, active C2.',
    members: [
      { persona: 'PER-0044', label: 'UNC-3312', role: 'operator' },
      { persona: 'PER-0031', label: 'UNC-2980', role: 'broker' }
    ],
    ttps: ['T1071.001', 'T1566.002', 'T1608'], cases: ['CASE-2026-0417'] },
  { id: 'CREW-001', name: 'LulzSec (revival)', tier: 'high', aka: ['lulzsec', 'lulz'],
    first_seen: '2026-03', assessment: 'Reputation-driven collective; opportunistic defacement and leak activity. Loose membership, high churn.',
    members: [ { persona: 'PER-0019', label: 'UNC-2201', role: 'poster' } ],
    ttps: ['T1583', 'T1567'], cases: ['CASE-2026-0371'] }
];

// ── Evidence: shared tier tone + documents / attachments / reclassify ────────
export const tierTone = (t) => (t === 'classified' ? 'critical' : t === 'restricted' ? 'high' : 'neutral');

const CLS_CLASSIFIED = {
  tier: 'classified', fail_closed: false, consult_llm: false, ruleset_version: 'v4', pii_map_version: 'v2',
  provenance: [
    { stage: 'extraction', tier_floor: 'normal', fail_closed: false },
    { stage: 'regex', tier_floor: 'classified', fail_closed: false },
    { stage: 'presidio', tier_floor: 'restricted', fail_closed: false },
    { stage: 'metadata', tier_floor: 'normal', fail_closed: false }
  ],
  regex_matches: [{ rule: 'iban_marker', tier_floor: 'classified', start: 412, end: 444, lang: 'en', matched_text: 'GB●●●●●●●●●●●●' }],
  presidio_matches: [{ entity_type: 'CREDIT_CARD', tier_floor: 'restricted', start: 88, end: 104, language: 'en', score: 0.99, matched_text: '●●●●●●●●●●●●1234' }],
  review_flags: [{ kind: 'llm_higher_tier', detail: 'model judged content more sensitive', suggested_tier: 'classified', corroborated: false }],
  llm: { suggested_tier: 'classified', confidence: 'medium', model: 'ollama/llama', attempts: 1 }
};
const CLS_NORMAL = {
  tier: 'normal', fail_closed: false, consult_llm: true, ruleset_version: 'v4', pii_map_version: 'v2',
  provenance: [
    { stage: 'extraction', tier_floor: 'normal', fail_closed: false },
    { stage: 'regex', tier_floor: 'normal', fail_closed: false },
    { stage: 'presidio', tier_floor: 'normal', fail_closed: false }
  ],
  regex_matches: [], presidio_matches: [], review_flags: []
};
const CLS_RESTRICTED = {
  tier: 'restricted', fail_closed: false, consult_llm: true, ruleset_version: 'v4', pii_map_version: 'v2',
  provenance: [
    { stage: 'extraction', tier_floor: 'normal', fail_closed: false },
    { stage: 'regex', tier_floor: 'normal', fail_closed: false },
    { stage: 'presidio', tier_floor: 'restricted', fail_closed: false }
  ],
  regex_matches: [],
  presidio_matches: [{ entity_type: 'CREDIT_CARD', tier_floor: 'restricted', start: 210, end: 226, language: 'en', score: 0.97, matched_text: '●●●●●●●●●●●●7788' }],
  review_flags: [{ kind: 'possible_over_classification', detail: 'FP-prone rule alone drove the tier', suggested_tier: 'normal', corroborated: false }]
};

export const DOCUMENTS = [
  { document_id: 'DOC-0455', filename: 'DSR-2026-NH-00417.docx', doc_kind: 'docx',
    content_mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    content_size: 48213, content_hash: 'a3f19e2c4b7d…b8d4', classifier_tier: 'classified', tier: 'classified',
    review_required: true, uploaded_at: '2026-09-20 08:38Z', ingested_at: '2026-09-20 08:40Z',
    classification: CLS_CLASSIFIED,
    extracted_text: '{"dump":"supplier-portal","records":2,"rows":[{"user":"a.reyes","hash":"$2b$12$…","iban":"GB●●●●●●●●●●●●"},{"user":"svc","card":"●●●●●●●●●●●●1234"}]}' },
  { document_id: 'DOC-0461', filename: 'press-release.pdf', doc_kind: 'pdf', content_mime: 'application/pdf',
    content_size: 91002, content_hash: '1b83c07d…9f22', classifier_tier: 'normal', tier: 'normal',
    review_required: false, uploaded_at: '2026-09-19 14:02Z', ingested_at: '2026-09-19 14:02Z',
    classification: CLS_NORMAL,
    extracted_text: 'FOR IMMEDIATE RELEASE. The consortium announced today a routine update to its public advisory program. No sensitive material is contained herein.' },
  { document_id: 'DOC-0448', filename: 'invoice-scan.pdf', doc_kind: 'pdf', content_mime: 'application/pdf',
    content_size: 210433, content_hash: 'aa419f22…c07d', classifier_tier: 'restricted', tier: 'restricted',
    review_required: true, uploaded_at: '2026-09-18 09:11Z', ingested_at: '2026-09-18 09:12Z',
    classification: CLS_RESTRICTED,
    extracted_text: 'INVOICE 2026-0448. Bill to: redacted. Payment card on file ending ●●●●7788. Net 30.' }
];
export const DOC_COLUMNS = [
  { key: 'document_id', header: 'Document', mono: true, width: '110px' },
  { key: 'filename', header: 'Filename', mono: true },
  { key: 'doc_kind', header: 'Kind', mono: true, width: '70px' },
  { key: 'tier', header: 'Tier', badge: true, tone: tierTone, width: '110px' },
  { key: 'uploaded_at', header: 'Uploaded', mono: true, align: 'right', width: '150px' }
];

export const ATTACHMENTS = [
  { blob_id: 'BLOB-7c1e', filename: 'screenshot.png', content_mime: 'image/png', content_size: 2048576,
    content_hash: '7c1e4d2a…b8d4', classifier_tier: 'normal', tier: 'normal',
    source_subject_kind: 'message', source_subject_id: 'MSG-88fd', collected_at: '2026-09-20 11:50Z' },
  { blob_id: 'BLOB-9a02', filename: 'dump.bin', content_mime: 'application/octet-stream', content_size: 512000,
    content_hash: '9a02f18c…4e1a', classifier_tier: 'restricted', tier: 'classified',
    source_subject_kind: 'observation', source_subject_id: 'OBS-9912', collected_at: '2026-09-20 12:01Z' },
  { blob_id: 'BLOB-3f51', filename: 'ledger.pdf', content_mime: 'application/pdf', content_size: 210433,
    content_hash: '3f51aa41…9f22', classifier_tier: 'restricted', tier: 'restricted',
    source_subject_kind: 'message', source_subject_id: 'MSG-90aa', collected_at: '2026-09-19 22:30Z' }
];
export const ATT_COLUMNS = [
  { key: 'blob_id', header: 'Blob', mono: true, width: '110px' },
  { key: 'filename', header: 'Filename', mono: true },
  { key: 'content_mime', header: 'MIME', mono: true, width: '150px' },
  { key: 'tier', header: 'Tier', badge: true, tone: tierTone, width: '110px' },
  { key: 'collected_at', header: 'Collected', mono: true, align: 'right', width: '150px' }
];

// Signed file-access journal rows (per blob). served_via = FileServedVia.
export const ACCESS_LOG = [
  { blob_id: 'BLOB-7c1e', served_at: '2026-09-20 11:57:40Z', user: 'op.vega', served_via: 'attachment_stream', tier: 'normal', request_id: 'req-7c1e-01' },
  { blob_id: 'BLOB-9a02', served_at: '2026-09-20 12:03:05Z', user: 'op.krieg', served_via: 'attachment_stream', tier: 'classified', request_id: 'req-9a02-04' },
  { blob_id: 'BLOB-9a02', served_at: '2026-09-20 12:05:11Z', user: 'op.krieg', served_via: 'thumbnail_only', tier: 'classified', request_id: 'req-9a02-05' }
];

// Recent reclassifications (ReclassificationResult).
export const RECLASSIFICATIONS = [
  { subject_id: 'BLOB-9a02', subject_kind: 'attachment', classifier_tier: 'restricted', operator_tier_override: 'classified',
    effective_tier: 'classified', prior_effective_tier: 'restricted', reclassified_at: '2026-09-20 09:20Z', decided_by: 'op.krieg', grant_id: 'GRANT-0039' },
  { subject_id: 'OBS-9912', subject_kind: 'observation', classifier_tier: 'normal', operator_tier_override: 'restricted',
    effective_tier: 'restricted', prior_effective_tier: 'normal', reclassified_at: '2026-09-18 16:44Z', decided_by: 'op.vega', grant_id: 'GRANT-0041' }
];
export const RECLASS_COLUMNS = [
  { key: 'subject_id', header: 'Subject', mono: true, width: '110px' },
  { key: 'subject_kind', header: 'Kind', mono: true, width: '110px' },
  { key: 'prior_effective_tier', header: 'From', badge: true, tone: tierTone, width: '110px' },
  { key: 'effective_tier', header: 'To', badge: true, tone: tierTone, width: '110px' },
  { key: 'decided_by', header: 'By', mono: true, width: '100px' },
  { key: 'reclassified_at', header: 'When', mono: true, align: 'right', width: '150px' }
];

// ── Identities (pool) ────────────────────────────────────────────────────────
// state: available | claimed | frozen | burned
const IDENTITY_TONE = { available: 'neutral', claimed: 'high', frozen: 'medium', burned: 'critical' };
export const identityTone = (s) => IDENTITY_TONE[s] ?? 'neutral';

export const IDENTITIES = [
  { id: 'ID-0071', platform: 'telegram', handle: '@relay_ferro',   state: 'claimed',   claimedBy: 'tg-collector-02', lastUsed: '2026-09-20 12:01Z' },
  { id: 'ID-0069', platform: 'telegram', handle: '@nord_watch',    state: 'available', claimedBy: '·',               lastUsed: '2026-09-18 22:14Z' },
  { id: 'ID-0064', platform: 'matrix',   handle: '@obs:svc.im',    state: 'frozen',    claimedBy: '·',               lastUsed: '2026-09-15 08:40Z' },
  { id: 'ID-0058', platform: 'telegram', handle: '@ghost_ingest',  state: 'burned',    claimedBy: '·',               lastUsed: '2026-09-10 03:12Z' },
  { id: 'ID-0055', platform: 'matrix',   handle: '@scribe:svc.im',  state: 'claimed',   claimedBy: 'mx-collector-01', lastUsed: '2026-09-20 11:58Z' },
  { id: 'ID-0051', platform: 'telegram', handle: '@quiet_probe',   state: 'available', claimedBy: '·',               lastUsed: '2026-09-19 17:02Z' }
];

export const IDENTITY_COLUMNS = [
  { key: 'id', header: 'Identity', mono: true, width: '96px' },
  { key: 'platform', header: 'Platform', mono: true, width: '90px' },
  { key: 'handle', header: 'Handle', mono: true },
  { key: 'state', header: 'State', badge: true, tone: identityTone, width: '110px' },
  { key: 'claimedBy', header: 'Claimed by', mono: true, width: '150px' },
  { key: 'lastUsed', header: 'Last used', mono: true, align: 'right', width: '160px' }
];

// ── Candidates (GroupCandidate triage) ───────────────────────────────────────
// state: pending | requested | approved | parked | rejected
const CANDIDATE_TONE = { pending: 'high', requested: 'high', approved: 'neutral', parked: 'low', rejected: 'medium' };
export const candidateTone = (s) => CANDIDATE_TONE[s] ?? 'neutral';

export const CANDIDATES = [
  { id: 'GC-2211', group: 'loader-ops-2',       platform: 'telegram', state: 'pending',   mentions: 14, via: 'ACT-3312 mention', found: '2026-09-20 10:11Z' },
  { id: 'GC-2208', group: '#staging-relay',     platform: 'matrix',   state: 'requested', mentions: 3,  via: 'invite-link',        found: '2026-09-20 08:44Z' },
  { id: 'GC-2201', group: 'fin-sector-chat',    platform: 'telegram', state: 'pending',   mentions: 9,  via: 'ACT-2980 mention',   found: '2026-09-19 21:30Z' },
  { id: 'GC-2194', group: 'carding-lounge',     platform: 'telegram', state: 'approved',  mentions: 22, via: 'seed-root',          found: '2026-09-18 14:02Z' },
  { id: 'GC-2190', group: 'random-memes-88',    platform: 'telegram', state: 'parked',    mentions: 1,  via: 'ACT-1774 mention',   found: '2026-09-18 09:15Z' },
  { id: 'GC-2185', group: 'spam-bulk-relay',    platform: 'matrix',   state: 'rejected',  mentions: 0,  via: 'crawl',              found: '2026-09-17 03:50Z' }
];

export const CANDIDATE_COLUMNS = [
  { key: 'id', header: 'Candidate', mono: true, width: '96px' },
  { key: 'group', header: 'Group', mono: true },
  { key: 'platform', header: 'Platform', mono: true, width: '90px' },
  { key: 'state', header: 'State', badge: true, tone: candidateTone, width: '110px' },
  { key: 'mentions', header: 'Mentions', mono: true, align: 'right', width: '90px' },
  { key: 'found', header: 'Discovered', mono: true, align: 'right', width: '160px' }
];
