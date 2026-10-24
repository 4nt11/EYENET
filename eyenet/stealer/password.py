# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stealer-log channel message parser — recover an archive password from the promo post.

Productionizes development/poc-tgmsg/msg_parse.py. Stealer channels bury a "Pass:" line
in a banner and watermark the password with their own channel handle/link (self-
watermarking: the password IS ``@theirhandle`` or ``t.me/theirhandle``). We anchor-search
(NOT anchor-at-start) for the pass line, fold homoglyph evasion first, then classify the
value: channel link / invite link / literal. A link-only fallback infers the dominant
``t.me`` link as an origin candidate when there's no explicit Pass label.

The message body is UNTRUSTED adversary input, so all matching is RE2
([[feedback_use_re2_for_untrusted_regex]]), never Python ``re``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import re2

# Homoglyph defang: channels swap Cyrillic/Greek lookalikes into "pass" (pаss) to dodge
# keyword filters. Fold the common confusables to Latin before anchoring; this also
# canonicalizes a channel handle so one operator isn't split across scripts.
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",  # cyrillic a e o p c
        "у": "y", "х": "x", "і": "i", "ѕ": "s", "ј": "j",  # y x i s j
        "к": "k", "м": "m", "т": "t", "н": "h", "в": "b",  # k m t h b
        "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C",
        "У": "Y", "Х": "X", "І": "I", "К": "K", "М": "M",
        "Т": "T", "Н": "H", "В": "B",
        "ο": "o", "α": "a", "ρ": "p", "ε": "e", "ι": "i",  # greek o a p e i
        "υ": "u", "τ": "t", "κ": "k", "χ": "x",
        "Ο": "O", "Α": "A", "Ρ": "P", "Ε": "E", "Ι": "I",
        "Κ": "K", "Τ": "T", "Χ": "X", "Β": "B", "Η": "H",
        "Μ": "M", "Ν": "N",
    }
)

# <emoji?> pass|password <delim> VALUE. Delimiter is ':'/'-' OR just whitespace
# ("Pass https://t.me/..."). Group 1 = delimiter, group 2 = value.
_ANCHOR = re2.compile(r"(?i)\bpass(?:word)?\b([ \t]*[:\-][ \t]*|[ \t]+)(\S+)")
_TME = re2.compile(r"(?i)(?:https?://)?t\.me/(\+?[A-Za-z0-9_]+)")
_HANDLE = re2.compile(r"(?i)^@([a-z][a-z0-9_]{3,})")


@dataclass(frozen=True, slots=True)
class ParsedPassword:
    """A password extracted (or inferred) from a stealer-channel promo message.

    ``password`` is the string to try against the archive (None = inferred link-only,
    no labeled pass). ``kind`` ∈ {channel_link, invite_link, literal, link_only,
    invite_only}. ``channel`` is the watermark handle — provenance + a discovery
    candidate — or None for a literal password.
    """

    password: str | None
    kind: str
    channel: str | None


def _defang(s: str) -> str:
    return s.translate(_CONFUSABLES)


def parse_password(body: str) -> ParsedPassword | None:
    """Recover the archive password from a stealer-channel message body, or None.

    Stage 1: the first Pass-anchored value that resolves to a t.me link, an @handle,
    or (only with a real ':'/'-' delimiter) a literal. Stage 2 fallback: no Pass label
    → the dominant t.me link is the origin/password CANDIDATE (password=None).
    """
    text = _defang(body or "")
    for m in _ANCHOR.finditer(text):
        delim, raw = m.group(1), m.group(2)
        tm = _TME.search(raw)
        if tm:
            ch = tm.group(1)
            kind = "invite_link" if ch.startswith("+") else "channel_link"
            return ParsedPassword(password=raw, kind=kind, channel=ch)
        h = _HANDLE.match(raw)
        if h:
            return ParsedPassword(password=raw, kind="channel_link", channel=h.group(1))
        if ":" in delim or "-" in delim:  # literal pw only with a REAL delimiter
            return ParsedPassword(password=raw, kind="literal", channel=None)
        # "pass <word>" (no delimiter, not a link), e.g. "password protected" → keep scanning
    links = _TME.findall(text)
    if links:
        public = [x for x in links if not x.startswith("+")]
        pick = Counter(public or links).most_common(1)[0][0]
        kind = "invite_only" if pick.startswith("+") else "link_only"
        return ParsedPassword(password=None, kind=kind, channel=pick)
    return None


def password_candidates(parsed: ParsedPassword | None) -> list[str]:
    """Ordered password strings to try against the archive, most-likely first.

    The self-watermark password is usually the handle WITH the leading '@' (proven:
    '@CloudHesoyam' opens the RAR, 'CloudHesoyam' does not) — but channels vary, so we
    also try the bare handle and the raw value. Empty list = try no-password (many
    archives are unencrypted)."""
    if parsed is None or parsed.password is None:
        return []
    out: list[str] = [parsed.password]
    if parsed.channel and f"@{parsed.channel}" not in out:
        out.append(f"@{parsed.channel}")
    if parsed.channel and parsed.channel not in out:
        out.append(parsed.channel)
    return out


__all__ = ["ParsedPassword", "parse_password", "password_candidates"]
