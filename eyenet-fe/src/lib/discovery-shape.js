// A group candidate's REAL platform and how it was DISCOVERED are derivable from
// its platform_groupid shape + kind_hint — independent of the SOURCE it was
// observed on. A Telegram @handle pulled from a forum post is a telegram
// candidate observed VIA a forum, not a forum group. The list view resolves the
// source's platform for the Platform column, which lies for these cross-platform
// leads; derive the truth from the shape instead.

const isMatrixAlias = (id) => /^#[^:\s]+:[^:\s]+$/.test(id);

// The GroupKind IS the platform signal — forums ONLY have forum_category (and
// forum_thread); chat/channel/dm are Telegram, matrix_room is Matrix. A Telegram
// chat has a numeric id (no @), so the id SHAPE can't be trusted; kind can. Shape
// is only the fallback for an unresolved mention that has no kind yet.
export function realPlatform(platformGroupId, kind) {
  const k = (kind ?? '').toLowerCase();
  if (k === 'forum_category' || k === 'forum_thread') return 'forum';
  if (k === 'matrix_room') return 'matrix';
  if (k === 'chat' || k === 'channel' || k === 'dm') return 'telegram';
  if (k === 'irc_channel') return 'irc';
  const id = platformGroupId ?? '';
  if (isMatrixAlias(id)) return 'matrix';
  // forum is forum_category ONLY, so a bare un-kinded mention is never forum.
  return 'telegram';
}

// How the candidate surfaced. forum_category/thread came from subforum
// enumeration; a group the operator's own account is in was seen in dialogs; the
// rest are post references (invite link / matrix alias / @mention).
export function foundVia(platformGroupId, kind, memberDialog) {
  const k = (kind ?? '').toLowerCase();
  if (k === 'forum_category' || k === 'forum_thread') return 'subforum';
  if (memberDialog) return 'dialog';
  const id = platformGroupId ?? '';
  if (id.startsWith('joinchat:')) return 'invite link';
  if (isMatrixAlias(id)) return 'matrix alias';
  return 'mention';
}

// The distinct real platforms, for a filter dropdown.
export const PLATFORMS = ['forum', 'telegram', 'matrix'];
