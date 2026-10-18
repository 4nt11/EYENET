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
  // Graph display taxonomy (same frozen backend model; the real entityType is kept for
  // enrichment calls, these are DISPLAY-only). See computeDisplayType().
  monitored_group: 'Monitored Group', // TG group/channel/chat we monitor
  monitored_category: 'Monitored Category', // a forum board/section
  post: 'Post' // a forum post (a MessageTable row inside a forum thread)
};
export const entityTypeLabel = (t) => label(ENTITY_TYPE_LABELS, t);

// Enrichment name -> human label for the right-click menu (no raw machine tokens). Unknown
// names (a dropped-in plugin) fall back to Title Case via label().
export const ENRICHMENT_LABELS = {
  messages: 'Messages',
  artifacts: 'Infrastructure',
  groups: 'Groups & threads',
  started: 'Threads started',
  replied_in: 'Replied in',
  linked: 'Linked actors',
  related: 'Related actors',
  source: 'Source',
  actors: 'Actors',
  connected_wallets: 'Connected wallets',
  domain: 'Host / domain',
  author: 'Author',
  container: 'Container',
  participants: 'Participants',
  op: 'Original poster',
  wallets: 'Wallets'
};
export const enrichmentLabel = (n) => label(ENRICHMENT_LABELS, n);

// Graph display type: the overloaded `group`/`message` entities map to the clean taxonomy
// ANTI set - monitored group (TG) vs monitored category (forum); message (TG) vs post
// (forum). The real entityType is untouched (enrichment calls still use it).
//
// NOTE: message -> post needs `fields.container_kind` ('forum_thread') which message_doc
// does NOT carry yet - a backend add + reindex. Until then every message shows as
// 'message'; once wired, forum posts render RED (--etype-post) as a "verify me" marker.
export function computeDisplayType(entityType, fields = {}, _status = null) {
  if (entityType === 'group')
    return fields?.kind === 'forum_category' ? 'monitored_category' : 'monitored_group';
  if (entityType === 'message')
    return fields?.container_kind === 'forum_thread' ? 'post' : 'message';
  return entityType;
}
export const nodeDisplayType = (n) =>
  n ? computeDisplayType(n.entityType, n.fields, n.status) : undefined;
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
