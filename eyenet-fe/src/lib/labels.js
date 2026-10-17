// Single source of truth for internal-slug -> human display labels across the FE.
// The backend stores internal slugs (pgp_key, wallet_btc, ipv4, UNRESOLVED, …);
// the UI must NEVER render those raw. One dictionary: find it here, change it here.
//
// Add a new mapping by adding a map below + (optionally) a small named helper.
// `label(map, key)` is the generic accessor and title-cases any unknown slug, so
// an operator-custom kind still reads as words, never `foo_bar`.

const titleCase = (s) =>
  String(s)
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');

/** Generic: map[key], else title-cased slug. Never returns a raw underscored slug. */
export function label(map, key) {
  if (!key) return '';
  return map[key] ?? titleCase(key);
}

// --- Infrastructure artifact kinds (eyenet/contracts/enums.py InfrastructureKind + coded) ---
export const ARTIFACT_KIND_LABELS = {
  domain: 'Domain',
  url: 'URL',
  onion: 'Onion',
  ipv4: 'IPv4',
  ipv6: 'IPv6',
  email: 'Email',
  wallet_btc: 'BTC Wallet',
  wallet_eth: 'ETH Wallet',
  wallet_xmr: 'XMR Wallet',
  wallet_tron: 'TRON Wallet',
  handle_other_platform: 'Handle',
  session: 'Session',
  tox: 'Tox',
  pgp_key: 'GPG Key'
};
export const ARTIFACT_KIND_ORDER = Object.keys(ARTIFACT_KIND_LABELS);
export const kindLabel = (k) => label(ARTIFACT_KIND_LABELS, k);

// --- Artifact bridge-resolution states (ResolutionState) ---
export const RESOLUTION_STATE_LABELS = {
  RESOLVED: 'Resolved',
  UNRESOLVED: 'Unresolved',
  AMBIGUOUS: 'Ambiguous',
  NOT_APPLICABLE: 'N/A'
};
export const resolutionLabel = (r) => label(RESOLUTION_STATE_LABELS, r);

// --- Incident taxonomy leaf names (the ordered list, group hierarchy and tones
// stay in lib/data.js — those are taxonomy structure + color, not translation).
// Names track development/incident-taxonomy-hierarchy.md. ---
export const INCIDENT_LABEL_NAMES = {
  defacement: 'Defacement',
  ddos_attack: 'DDoS Attack',
  intrusion: 'Intrusion',
  breach_dump: 'Breach Dump',
  credentials: 'Credentials',
  stealer_logs: 'Stealer Logs',
  iab_corporate: 'Initial Access Broker',
  crimeware_tooling: 'Crimeware Tooling',
  crime_aas: 'Crime-as-a-Service',
  telecom_abuse: 'Telecom Abuse',
  phishing_delivery: 'Phishing Delivery',
  fraud_ops: 'Fraud Operations',
  infra_resale: 'Infrastructure Resale',
  recruiting: 'Recruiting',
  alliance: 'Alliance',
  crew_ops: 'Crew Operations'
};
export const incidentLabelName = (l) => label(INCIDENT_LABEL_NAMES, l);

// --- Threat tier -> severity word ---
export const THREAT_LABELS = {
  critical: 'Severe',
  high: 'Elevated',
  medium: 'Moderate',
  low: 'Guarded'
};
export const threatLabel = (t) => label(THREAT_LABELS, t);

// --- Entity type -> singular human label (badges, graph result rows) ---
export const ENTITY_TYPE_LABELS = {
  actor: 'Actor',
  persona: 'Persona',
  crew: 'Crew',
  group: 'Group',
  thread: 'Thread',
  message: 'Message',
  artifact: 'Artifact',
  document: 'Document',
  attachment: 'Attachment',
  case: 'Case',
  incident: 'Incident',
  mention: 'Mention',
  source: 'Source',
  // Graph display sub-types of the overloaded `group` entity (same backend entity_type,
  // distinguished by GroupKind + lifecycle status). See groupDisplayType().
  forum_category: 'Forum Category',
  monitored_group: 'Monitored Group',
  candidate_group: 'Candidate Group'
};
export const entityTypeLabel = (t) => label(ENTITY_TYPE_LABELS, t);

// The `group` entity is overloaded (TG chats/channels AND forum categories AND threads,
// at candidate/joined/monitored/known lifecycle). For the graph we show a derived display
// sub-type - the real entityType stays "group" for enrichment calls (type=group).
export function groupDisplayType(fields = {}, status = null) {
  if (fields?.kind === 'forum_category') return 'forum_category';
  if (status === 'candidate') return 'candidate_group';
  if (status === 'monitored' || status === 'joined') return 'monitored_group';
  return 'group';
}

// Display type for ANY node: group nodes get the derived sub-type, everything else is its
// own entityType. Used for color + label so the real entityType is untouched.
export const nodeDisplayType = (n) =>
  n?.entityType === 'group' ? groupDisplayType(n.fields, n.status) : n?.entityType;
export const nodeTypeLabel = (n) => entityTypeLabel(nodeDisplayType(n));

// --- Entity type -> nav section it opens in ---
export const ENTITY_ROUTE_LABELS = {
  actor: 'Actors',
  persona: 'Personas',
  case: 'Cases',
  group: 'Monitored groups',
  thread: 'Monitored groups'
};

// --- Group kind -> short display word (reader) ---
export const GROUP_KIND_LABELS = {
  forum_category: 'forum',
  forum_thread: 'thread',
  channel: 'channel',
  chat: 'chat',
  matrix_room: 'room'
};
export const groupKindLabel = (k) => label(GROUP_KIND_LABELS, k);

/** Capitalize the first letter only (e.g. an entity type: actor -> Actor). */
export const capitalize = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
