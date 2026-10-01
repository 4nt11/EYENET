// A group candidate's REAL platform and how it was DISCOVERED are derivable from
// its platform_groupid shape + kind_hint — independent of the SOURCE it was
// observed on. A Telegram @handle pulled from a forum post is a telegram
// candidate observed VIA a forum, not a forum group. The list view resolves the
// source's platform for the Platform column, which lies for these cross-platform
// leads; derive the truth from the shape instead.

const isMatrixAlias = (id) => /^#[^:\s]+:[^:\s]+$/.test(id);

// telegram (@handle / joinchat invite) | matrix (#room:server) | forum (native).
export function realPlatform(platformGroupId) {
  const id = platformGroupId ?? '';
  if (id.startsWith('@') || id.startsWith('joinchat:')) return 'telegram';
  if (isMatrixAlias(id)) return 'matrix';
  return 'forum';
}

// How the candidate surfaced. kind_hint is set only by forum subforum
// enumeration; mentions/invite links carry none. member_dialog is a separate
// axis (the member segment), not a discovery method, so it is NOT folded in.
export function foundVia(platformGroupId, kindHint) {
  const id = platformGroupId ?? '';
  if (kindHint) return 'subforum';
  if (id.startsWith('joinchat:')) return 'invite link';
  if (isMatrixAlias(id)) return 'matrix alias';
  return 'mention';
}

// The distinct real platforms, for a filter dropdown.
export const PLATFORMS = ['forum', 'telegram', 'matrix'];
