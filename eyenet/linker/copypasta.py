# SPDX-License-Identifier: AGPL-3.0-or-later
"""Copypasta / near-duplicate template detection (anti-spam linkage §A).

Templated spam defeats stylometric authorship linkage: a long ad pasted verbatim
by a bot fleet gives every poster an identical char-ngram fingerprint, so simhash
proposes them as "same author" (and the Verifier's NCD agrees — identical text
compresses identically). The fix is to *identify* the template and gate authorship
linkage on it, so writing-style comparison only ever sees an actor's own words.

This module is the pure detection core: a body -> a **masked fingerprint**. The
mask (numbers, @handles, urls, wallets, emoji, punctuation collapsed away) makes
"same ad, different amount/handle" hash to one template — and, deliberately, the
*varying* slots that fall out are exactly the infrastructure the §B linker keys
on. Occurrence counting + persistence + the sensor gate live in storage + the
sensor; here there is no I/O.

See ``development/linker-antispam-spec.md`` §2.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# A template must be at least this long (normalized chars) and posted by at least
# this many distinct actors to count as copypasta. Both tunable per operator;
# defaults calibrated on the live USDT/UPI/CVV ad corpus (~300-1500 chars, 3-27
# posters). A single long message from one account is NOT copypasta.
TEMPLATE_MIN_CHARS = 200
TEMPLATE_MIN_ACTORS = 3

_URL = re.compile(r"(?:https?://|t\.me/)\S+", re.IGNORECASE)
_WALLET = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b|\b0x[a-fA-F0-9]{40}\b")
_HANDLE = re.compile(r"@[A-Za-z0-9_]+")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)  # strips emoji + punctuation, keeps letters/digits/_
_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def normalize_for_template(body: str) -> str:
    """Collapse a message to its template form: case-folded, with the volatile
    slots (urls, wallets, @handles, numbers) masked to fixed tokens and emoji /
    punctuation removed. Non-Latin letters (the ad copy itself) are preserved, so
    the template text is the identity."""
    t = unicodedata.normalize("NFKC", body).lower()
    t = _URL.sub(" urlx ", t)
    t = _WALLET.sub(" walletx ", t)
    t = _HANDLE.sub(" handlex ", t)
    t = _NONWORD.sub(" ", t)  # emoji + punctuation -> space
    t = _DIGITS.sub("0", t)  # mask amounts / ids
    return _WS.sub(" ", t).strip()


def template_fingerprint(body: str) -> str:
    """SHA-256 of the normalized template form. Two verbatim reposts (or the same
    ad with a swapped amount/handle) share a fingerprint."""
    return hashlib.sha256(normalize_for_template(body).encode("utf-8")).hexdigest()


def is_copypasta(char_len: int, distinct_actors: int) -> bool:
    """A template is copypasta once it is long enough AND spread across enough
    distinct posters."""
    return char_len >= TEMPLATE_MIN_CHARS and distinct_actors >= TEMPLATE_MIN_ACTORS


__all__ = [
    "TEMPLATE_MIN_ACTORS",
    "TEMPLATE_MIN_CHARS",
    "is_copypasta",
    "normalize_for_template",
    "template_fingerprint",
]
