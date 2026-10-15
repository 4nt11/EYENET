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
  pgp_key: 'GPG Key',
  paste_url: 'Paste URL'
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
