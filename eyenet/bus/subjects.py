"""NATS-style subject matching.

Wildcards:
  `*`  — matches a single token (one segment between dots).
  `>`  — matches one or more trailing tokens. Only legal as the last token.

Pure function, no I/O. Used by `MemoryBus`; `NATSBus` delegates to the
server-side matcher.
"""

from __future__ import annotations


def _split(s: str) -> list[str]:
    return s.split(".") if s else []


def subject_matches(pattern: str, subject: str) -> bool:
    """Return True iff `subject` matches `pattern` per NATS rules."""

    p = _split(pattern)
    s = _split(subject)
    i = 0
    for tok in p:
        if tok == ">":
            return i < len(s)
        if i >= len(s):
            return False
        if tok == "*":
            i += 1
            continue
        if tok != s[i]:
            return False
        i += 1
    return i == len(s)


def is_valid_pattern(pattern: str) -> bool:
    """Reject malformed patterns (`>` not last, empty tokens)."""

    if not pattern:
        return False
    tokens = pattern.split(".")
    for idx, t in enumerate(tokens):
        if not t:
            return False
        if t == ">" and idx != len(tokens) - 1:
            return False
    return True


__all__ = ["is_valid_pattern", "subject_matches"]
