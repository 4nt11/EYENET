"""Lexical primitive: lexical.vocabulary_richness (MATTR).

Moving-Average Type-Token Ratio over a sliding window of 50 tokens.
Volume-independent: each window contributes its own TTR; value is the mean.
Avoids the standard TTR bias where larger corpora mechanically score lower.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

PRIMITIVE_NAME = "lexical.vocabulary_richness"
PRIMITIVE_VERSION = "0.2"
WINDOW_SIZE = 50
MIN_TOKENS = 100

_WORD_RE = re.compile(r"\S+")


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


def _mattr(tokens: list[str], window: int) -> float:
    """Compute MATTR. Returns 0.0 if fewer tokens than one window."""
    if len(tokens) < window:
        return len(set(tokens)) / len(tokens) if tokens else 0.0
    ttrs = []
    for i in range(len(tokens) - window + 1):
        w = tokens[i : i + window]
        ttrs.append(len(set(w)) / window)
    return sum(ttrs) / len(ttrs)


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    all_tokens: list[str] = []
    for _, _, ref in corpus:
        if ref in bodies:
            all_tokens.extend(_tokenize(bodies[ref]))

    if len(all_tokens) < MIN_TOKENS:
        return None

    value = _mattr(all_tokens, WINDOW_SIZE)

    ts_vals = [ts.timestamp() for ts, _, _ in corpus]
    window = Window(start_ts=min(ts_vals), end_ts=max(ts_vals))

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=round(value, 6),
        confidence=min(1.0, len(all_tokens) / 1000),
        window=window,
        source=f"eyenet/sensor/primitives/mattr-w{WINDOW_SIZE}:v{PRIMITIVE_VERSION}",
        evidence_ref=corpus[-1][2] if corpus else None,
        ts=time.time(),
    )


__all__ = ["MIN_TOKENS", "PRIMITIVE_NAME", "PRIMITIVE_VERSION", "WINDOW_SIZE", "compute"]
