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

from typing import NamedTuple

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

# Default subforum-discovery depth when no level is chosen. 0 = index top-level
# categories only (one request); >=1 descends into each forum's page for child
# subforums (one request PER forum, which is what makes discovery expensive).
DEFAULT_DISCOVERY_DEPTH = 2

# -- evasion templates (nmap -T analog) ---------------------------------------
# Operator picks a level per identity; expanded to concrete knobs (forum_delay_
# min/max + forum_discovery_depth) at provision time. E1 "lurker" is validated
# live (zero 429s on a defended onion forum). Slowest/quietest (ghost) → loudest
# (smash). discovery_depth 0 = index only: the index is ONE request that already
# lists every top-level category (free intel); subforum descent is the costly bit
# a ghost defers (add subforums by hand via the API, or bump the level later).


class EvasionProfile(NamedTuple):
    delay_min: float  # inter-request delay floor (s)
    delay_max: float  # inter-request delay ceiling (s)
    discovery_depth: int  # subforum BFS depth at (re)subscribe; 0 = index only


EVASION_LEVELS: dict[str, EvasionProfile] = {
    "ghost": EvasionProfile(90.0, 240.0, 0),  # E0: index only, no subforum walk
    "lurker": EvasionProfile(20.0, 60.0, 1),  # E1: validated; one subforum level
    "regular": EvasionProfile(8.0, 15.0, 2),  # E2
    "brisk": EvasionProfile(3.0, 6.0, 2),  # E3
    "smash": EvasionProfile(0.5, 1.5, 2),  # E4: tolerant boards only (no limiter)
}
# nmap-style aliases so an operator can say "E1" instead of "lurker".
_EVASION_ALIASES = {"e0": "ghost", "e1": "lurker", "e2": "regular", "e3": "brisk", "e4": "smash"}


def resolve_evasion_profile(level: str | None) -> EvasionProfile | None:
    """Map an evasion level name to its EvasionProfile, or None for an absent/
    unknown level. Applied at provision time so the collector only ever sees
    concrete knobs. Case/space-insensitive; also accepts the E0..E4 aliases."""
    if not level:
        return None
    key = level.strip().lower()
    return EVASION_LEVELS.get(_EVASION_ALIASES.get(key, key))


if __name__ == "__main__":  # human-readable dump: `python -m ...` to eyeball the profiles
    for i, (name, p) in enumerate(EVASION_LEVELS.items()):
        depth = "index only" if p.discovery_depth == 0 else f"depth {p.discovery_depth}"
        print(f"E{i} {name:8} {p.delay_min:6.1f}-{p.delay_max:5.1f}s/req  {depth}")
    print(
        f"default {DEFAULT_DELAY_MIN}-{DEFAULT_DELAY_MAX}s depth {DEFAULT_DISCOVERY_DEPTH} | "
        f"429 backoff {DEFAULT_RETRY_AFTER}s + rand{RETRY_AFTER_PAD}s"
    )
