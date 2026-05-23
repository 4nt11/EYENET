"""Stylometric primitive: distinctive_vocabulary_signature.

64-bit simhash over a TF-IDF-weighted top-K rare-word vector. Per-actor IDF:
IDF is computed from the actor's own corpus window (user-chosen per PLAN §M2 design
decisions — preserves sensor statelesness across actors). Cross-actor comparability
is intentionally deferred to M4 calibration.

Strong against context-shift: rare words are where authorial choice lives.
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._simhash import simhash64

PRIMITIVE_NAME = "stylometric.distinctive_vocabulary_signature"
PRIMITIVE_VERSION = "0.2"
TOP_K = 50
MIN_MESSAGES = 50

_WORD_RE = re.compile(r"[a-záéíóúüñàèìòùâêîôûäëïöü]{3,}", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    docs = [bodies[ref] for _, _, ref in corpus if ref in bodies]
    if len(docs) < MIN_MESSAGES:
        return None

    tokenized = [_tokenize(d) for d in docs]
    n_docs = len(tokenized)

    # Document frequency for IDF
    doc_freq: dict[str, int] = {}
    for tokens in tokenized:
        for w in set(tokens):
            doc_freq[w] = doc_freq.get(w, 0) + 1

    # Term frequency across entire corpus
    term_freq: dict[str, int] = {}
    for tokens in tokenized:
        for w in tokens:
            term_freq[w] = term_freq.get(w, 0) + 1

    total_tokens = sum(term_freq.values())
    if total_tokens == 0:
        return None

    # TF-IDF: tf * log((n_docs + 1) / (df + 1)) — smoothed IDF
    tfidf: dict[str, float] = {}
    for word, tf in term_freq.items():
        idf = math.log((n_docs + 1) / (doc_freq.get(word, 0) + 1)) + 1.0
        tfidf[word] = (tf / total_tokens) * idf

    # Take top-K by TF-IDF score
    top_words = sorted(tfidf, key=lambda w: tfidf[w], reverse=True)[:TOP_K]
    if not top_words:
        return None

    features = {w: tfidf[w] for w in top_words}
    fingerprint = simhash64(features)

    ts_vals = [ts.timestamp() for ts, _, _ in corpus]
    window = Window(start_ts=min(ts_vals), end_ts=max(ts_vals))

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=fingerprint,
        confidence=min(1.0, n_docs / 200),
        window=window,
        source=f"eyenet/sensor/primitives/tfidf-top{TOP_K}:v{PRIMITIVE_VERSION}",
        evidence_ref=corpus[-1][2] if corpus else None,
        ts=time.time(),
    )


__all__ = ["MIN_MESSAGES", "PRIMITIVE_NAME", "PRIMITIVE_VERSION", "TOP_K", "compute"]
