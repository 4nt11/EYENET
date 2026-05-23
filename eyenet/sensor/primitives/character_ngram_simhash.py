"""Stylometric primitive: character_ngram_simhash.

64-bit simhash over character trigram frequencies. Lowercased; accents preserved.
Captures punctuation tics, accent-stripping habits, and idiom-fragment fingerprints
that survive paraphrase. Orthogonal to function-word distributions.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._simhash import simhash64

PRIMITIVE_NAME = "stylometric.character_ngram_simhash"
PRIMITIVE_VERSION = "0.2"
NGRAM_SIZE = 3
MIN_TOKENS = 200


def _ngrams(text: str, n: int) -> list[str]:
    lower = text.lower()
    return [lower[i : i + n] for i in range(len(lower) - n + 1)]


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    bodies_list = [bodies[ref] for _, _, ref in corpus if ref in bodies]
    if not bodies_list:
        return None

    all_text = " ".join(bodies_list)
    token_count = len(all_text.split())
    if token_count < MIN_TOKENS:
        return None

    freq: dict[str, int] = {}
    for gram in _ngrams(all_text, NGRAM_SIZE):
        freq[gram] = freq.get(gram, 0) + 1

    if not freq:
        return None

    fingerprint = simhash64({k: float(v) for k, v in freq.items()})

    ts_vals = [ts.timestamp() for ts, _, _ in corpus]
    window = Window(start_ts=min(ts_vals), end_ts=max(ts_vals))

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=fingerprint,
        confidence=min(1.0, token_count / 1000),
        window=window,
        source=f"eyenet/sensor/primitives/char{NGRAM_SIZE}gram:v{PRIMITIVE_VERSION}",
        evidence_ref=corpus[-1][2] if corpus else None,
        ts=time.time(),
    )


__all__ = ["MIN_TOKENS", "PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
