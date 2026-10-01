# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum-collector timing profiles — the one place to read "how fast does it go".

Request-pacing and 429-backoff knobs for the MyBB/XenForo collector, pulled out
of ``real.py`` so an operator can eyeball the whole speed/stealth story at once.
The behaviour that USES these lives in ``real.py`` (the ``_get``/``_post``
cooldown gate and ``on_subscribe`` pacing); this file is pure data + the level
resolver. Full rationale + the live measurements that set these numbers:
``investigations/pwnforums/collection-profile.md``.
"""

from __future__ import annotations

# -- default pacing -----------------------------------------------------------
# Every request waits a jittered delay in [min, max] seconds; requests are
# strictly sequential. A live board bans an account that rips flat-out, so these
# are deliberately browsing-speed. Overridden per identity (an evasion level
# below, or explicit forum_delay_min/max).
DEFAULT_DELAY_MIN = 4.0
DEFAULT_DELAY_MAX = 12.0

# -- 429 backoff timing -------------------------------------------------------
# Fallback cooldown when a 429 carries no (or an unparseable) Retry-After. The
# measured pwnforums value; a conservative 10 min beats guessing low and poking.
DEFAULT_RETRY_AFTER = 600.0
# The server's cooldown timer RESETS on any request made during cooldown (measured
# on pwnforums), and resuming on the EXACT second is a robotic tell — so after a
# 429 we go silent for Retry-After PLUS this jitter pad, and never poke meanwhile.
RETRY_AFTER_PAD = (30.0, 120.0)

# -- evasion templates (nmap -T analog) ---------------------------------------
# Operator picks a level per identity; it seeds the inter-request [min, max]
# pacing (expanded to forum_delay_min/max at provision time). Page caps /
# discovery stay their own knobs. E1 "lurker" is validated live (zero 429s on a
# defended onion forum). Slowest (ghost) → fastest (smash):
EVASION_LEVELS: dict[str, tuple[float, float]] = {
    "ghost": (90.0, 240.0),  # E0: minutes apart, strict night-owl; hardest targets
    "lurker": (20.0, 60.0),  # E1: validated on a defended onion forum
    "regular": (8.0, 15.0),  # E2
    "brisk": (3.0, 6.0),  # E3
    "smash": (0.5, 1.5),  # E4: tolerant boards only (no such limiter)
}
# nmap-style aliases so an operator can say "E1" instead of "lurker".
_EVASION_ALIASES = {"e0": "ghost", "e1": "lurker", "e2": "regular", "e3": "brisk", "e4": "smash"}


def resolve_evasion_pacing(level: str | None) -> tuple[float, float] | None:
    """Map an evasion level name to its (delay_min, delay_max) pacing, or None for
    an absent/unknown level. Applied at provision time so the collector only ever
    sees concrete delays. Case/space-insensitive; also accepts the E0..E4 aliases."""
    if not level:
        return None
    key = level.strip().lower()
    return EVASION_LEVELS.get(_EVASION_ALIASES.get(key, key))


if __name__ == "__main__":  # human-readable dump: `python -m ...` to eyeball the profiles
    for i, (name, (lo, hi)) in enumerate(EVASION_LEVELS.items()):
        print(f"E{i} {name:8} {lo:6.1f}-{hi:5.1f}s")
    print(
        f"default {DEFAULT_DELAY_MIN}-{DEFAULT_DELAY_MAX}s | 429 backoff "
        f"{DEFAULT_RETRY_AFTER}s + rand{RETRY_AFTER_PAD}s"
    )
