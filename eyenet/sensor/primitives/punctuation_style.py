"""Stylometric primitive: punctuation_style.

64-bit simhash over the relative-frequency vector of canonical punctuation
patterns. Captures consistent punctuation tics (always-ellipsis, no-period,
dash-instead-of-comma) that survive topic changes. Hard for actors to fake
consistently under pressure.

Per BEHAVE-TEXT spec: HASH value kind. Used by `bot_or_automated_poster`
recipe (M5) to detect perfect-consistency bots.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._simhash import simhash64

PRIMITIVE_NAME = "stylometric.punctuation_style"
PRIMITIVE_VERSION = "0.1"
MIN_MESSAGES = 10
MIN_CHARS = 200

# Canonical punctuation tokens to track.
_PUNCT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.\.\."),  # ellipsis
    re.compile(r"!{2,}"),  # multiple exclamation
    re.compile(r"\?{2,}"),  # multiple question
    re.compile(r"(?<![.!?])\.(?!\d)"),  # single period (sentence-ending)
    re.compile(r","),  # comma
    re.compile(r";"),  # semicolon
    re.compile(r":"),  # colon
    re.compile(r"-{1,2}"),  # dash/hyphen
    re.compile(r"\""),  # double quote
    re.compile(r"'"),  # apostrophe / single quote
    re.compile(r"\(|\)"),  # parentheses
    re.compile(r"!(?!!|$)"),  # single exclamation
    re.compile(r"\?(?!\?)"),  # single question
)

_PUNCT_NAMES: tuple[str, ...] = (
    "ellipsis",
    "multi_excl",
    "multi_quest",
    "period",
    "comma",
    "semicolon",
    "colon",
    "dash",
    "dquote",
    "squote",
    "paren",
    "single_excl",
    "single_quest",
)


def _punct_freq(text: str) -> dict[str, float]:
    total_chars = max(len(text), 1)
    return {
        name: len(pat.findall(text)) / total_chars
        for name, pat in zip(_PUNCT_NAMES, _PUNCT_PATTERNS, strict=True)
    }


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    texts = [bodies[ref] for _, _, ref in corpus if ref in bodies]
    if len(texts) < MIN_MESSAGES:
        return None
    combined = " ".join(texts)
    if len(combined) < MIN_CHARS:
        return None

    freq = _punct_freq(combined)
    if not any(v > 0 for v in freq.values()):
        return None

    fingerprint = simhash64(freq)
    ts_vals = [ts.timestamp() for ts, _, _ in corpus]

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=fingerprint,
        confidence=min(1.0, len(texts) / 50),
        window=Window(start_ts=min(ts_vals), end_ts=max(ts_vals)),
        source=f"eyenet/sensor/primitives/punct_style:v{PRIMITIVE_VERSION}",
        evidence_ref=corpus[-1][2] if corpus else None,
        ts=time.time(),
    )


__all__ = ["MIN_CHARS", "MIN_MESSAGES", "PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
