"""Hostname normalization and SourceDomain pattern intersection (MODELS §2.26).

Two pure functions are exported:

* :func:`normalize_host` — canonicalizes an operator-supplied hostname into
  lowercase ASCII punycode (IDNA2008 + UTS46). The stdlib ``'idna'`` codec
  implements IDNA2003 and silently NFKC-folds adversarial input, which
  defeats homograph defense; we use the :mod:`idna` PyPI package instead
  (``uts46=True, transitional_processing=False``).

* :func:`patterns_intersect` — pure predicate over
  ``(pattern, pattern_kind)`` pairs that returns True iff some hostname is
  matched by both. Used by the storage layer's in-transaction overlap
  detection (:class:`SourcesMixin._detect_overlap_in_session`).

Everything in this module is side-effect-free and importable from any
layer without acquiring a session, a clock, or a logger.
"""

from __future__ import annotations

import idna

from eyenet.contracts.enums import SourceDomainPatternKind

_MAX_ASCII_CODEPOINT = 127


def normalize_host(value: str) -> str:
    """Return the canonical ASCII punycode form of a hostname.

    Steps, in order:

    1. Strip leading/trailing whitespace. Raise :class:`ValueError` if the
       result is empty.
    2. Strip exactly one trailing dot (``foo.com.`` → ``foo.com``).
    3. Reject mixed input: if the string contains ``xn--`` *and* any
       non-ASCII character, the caller has handed us a half-converted
       hostname (one label punycoded, another not). Raise.
    4. Encode via :func:`idna.encode` with ``uts46=True`` and
       ``transitional=False`` — IDNA2008 + UTS46 rejects confusable
       mixed-script labels that the stdlib codec passes through.
    5. Lowercase the resulting ASCII (punycode is case-insensitive at the
       DNS layer; we normalize to lower for byte-equal comparison).

    Idempotent: ``normalize_host(normalize_host(x)) == normalize_host(x)``.

    Raises :class:`ValueError` on any invalid input. Callers that want to
    surface domain-specific errors should catch and re-raise.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("empty host")
    if stripped.endswith("."):
        stripped = stripped[:-1]
        if not stripped:
            raise ValueError("empty host after stripping trailing dot")

    has_xn = "xn--" in stripped.lower()
    has_non_ascii = any(ord(ch) > _MAX_ASCII_CODEPOINT for ch in stripped)
    if has_xn and has_non_ascii:
        raise ValueError("ambiguous mixed-form host (both xn-- and unicode present)")

    try:
        encoded = idna.encode(stripped, uts46=True, transitional=False)
    except idna.IDNAError as exc:
        raise ValueError(f"invalid host {stripped!r}: {exc}") from exc
    return encoded.decode("ascii").lower()


def patterns_intersect(
    p1: str,
    k1: SourceDomainPatternKind,
    p2: str,
    k2: SourceDomainPatternKind,
) -> bool:
    """True iff some hostname is matched by both ``(p1, k1)`` and ``(p2, k2)``.

    Both patterns are assumed to already be in canonical form (output of
    :func:`normalize_host`). For ``subdomain_wildcard`` the ``pattern``
    holds the parent only (no ``*.`` prefix); this is enforced by a CHECK
    at the storage layer.

    Pairwise semantics (symmetric — argument order doesn't change the
    answer; the function commutes by swapping arguments):

    * ``exact + exact`` — same string.
    * ``exact + subdomain_wildcard`` — the exact host is a strict subdomain
      of the wildcard's parent.
    * ``exact + suffix_match`` — the exact host equals the suffix pattern
      or is a strict subdomain of it.
    * ``subdomain_wildcard + subdomain_wildcard`` — one parent is the
      other or a subdomain of the other (their reach overlaps).
    * ``subdomain_wildcard + suffix_match`` — the wildcard parent equals
      the suffix pattern, is its subdomain, or the suffix pattern is a
      strict subdomain of the wildcard parent.
    * ``suffix_match + suffix_match`` — one is the other or a subdomain
      of the other.

    All "is a subdomain" checks use label-boundary endswith
    (``host.endswith("." + parent)``) — naive ``str.endswith`` would
    consider ``foo.com`` a "subdomain" of ``oo.com``.
    """
    # Normalize argument order so we only write each pair once.
    pair = (k1, k2)
    if (k1.value, p1) > (k2.value, p2):
        # Swap so the rule matrix below stays compact; semantics are symmetric.
        p1, p2 = p2, p1
        k1, k2 = k2, k1
        pair = (k1, k2)

    exact = SourceDomainPatternKind.EXACT
    wildcard = SourceDomainPatternKind.SUBDOMAIN_WILDCARD
    suffix = SourceDomainPatternKind.SUFFIX_MATCH
    if pair == (exact, exact):
        return p1 == p2
    if pair == (exact, wildcard):
        # exact is p1, wildcard parent is p2
        return _is_strict_subdomain(p1, p2)
    if pair == (exact, suffix):
        return p1 == p2 or _is_strict_subdomain(p1, p2)
    if pair == (wildcard, wildcard):
        return _parents_reach_overlap(p1, p2)
    if pair == (wildcard, suffix):
        return _parents_reach_overlap(p1, p2)
    if pair == (suffix, suffix):
        return _parents_reach_overlap(p1, p2)
    # Unreachable: every (k1,k2) combination is enumerated above after the swap.
    raise AssertionError(f"unhandled pattern kind pair {pair!r}")


def pattern_matches_host(
    pattern: str,
    pattern_kind: SourceDomainPatternKind,
    host: str,
) -> bool:
    """True iff ``host`` is matched by the ``(pattern, pattern_kind)`` rule.

    Inputs are assumed canonical (output of :func:`normalize_host`). The
    semantics mirror :data:`SourceDomainPatternKind`'s docstring:

    * ``exact`` — string equality
    * ``subdomain_wildcard`` — host is a strict subdomain of the pattern
    * ``suffix_match`` — host equals the pattern or is a strict subdomain
    """
    if pattern_kind is SourceDomainPatternKind.EXACT:
        return host == pattern
    if pattern_kind is SourceDomainPatternKind.SUBDOMAIN_WILDCARD:
        return _is_strict_subdomain(host, pattern)
    if pattern_kind is SourceDomainPatternKind.SUFFIX_MATCH:
        return host == pattern or _is_strict_subdomain(host, pattern)
    raise AssertionError(f"unhandled pattern kind {pattern_kind!r}")


def _is_strict_subdomain(host: str, parent: str) -> bool:
    """True iff ``host`` is a strict subdomain of ``parent`` (label-boundary safe)."""
    return host.endswith("." + parent) and host != parent


def _parents_reach_overlap(a: str, b: str) -> bool:
    """True iff two parent-style patterns can match a common host.

    Two parents overlap if they're equal or one is a subdomain of the
    other. ``foo.com`` and ``bar.foo.com`` overlap (both match
    ``x.bar.foo.com``); ``foo.com`` and ``foo.net`` do not.
    """
    return a == b or _is_strict_subdomain(a, b) or _is_strict_subdomain(b, a)


__all__ = ["normalize_host", "pattern_matches_host", "patterns_intersect"]
