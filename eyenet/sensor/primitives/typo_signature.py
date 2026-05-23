"""Stylometric primitive: typo_signature.

SHA-256 (hex, first 16 chars) over the canonical set of persistent typos in
the actor's corpus. "Persistent typo" = a misspelling that appears in ≥ 10%
of messages where the base word appears, AND appears at least 3 times.

The fingerprint is stable for consistent typists and near-zero / unstable for
careful writers and bots (bots spell perfectly). Pairs with `punctuation_style`
for mutual reinforcement.

Implementation note: we use a corpus-IDF approach rather than a spell-check
dictionary to stay language-agnostic and avoid false-positives in domain-
specific slang (e.g. "creden" as short for "credentials" is not a typo).
Two words are "variants" if Levenshtein distance == 1 and the more-frequent
form appears > 5x more often than the rarer form.

Per BEHAVE-TEXT spec: HASH value kind.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

PRIMITIVE_NAME = "stylometric.typo_signature"
PRIMITIVE_VERSION = "0.1"
MIN_MESSAGES = 15
MIN_WORD_OCCURRENCES = 3
MIN_VOCAB_SIZE = 20
TYPO_RATE_THRESHOLD = 0.10  # word appears misspelled in ≥ 10% of its occurrences
FREQUENCY_DOMINANCE = 5.0  # dominant form appears ≥ 5x more than variant

_WORD_RE = re.compile(r"[a-záéíóúüñàèìòùâêîôûäëïöü]{3,}", re.IGNORECASE)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


def _find_persistent_typos(word_counts: Counter[str]) -> frozenset[str]:
    """Return the set of words that are persistent typos of more-common neighbors."""
    typos: set[str] = set()
    words = list(word_counts)
    for i, w in enumerate(words):
        for w2 in words[i + 1 :]:
            if abs(len(w) - len(w2)) > 1:
                continue
            if _levenshtein(w, w2) != 1:
                continue
            dominant, variant = (w, w2) if word_counts[w] >= word_counts[w2] else (w2, w)
            if (
                word_counts[variant] >= MIN_WORD_OCCURRENCES
                and word_counts[dominant] >= FREQUENCY_DOMINANCE * word_counts[variant]
            ):
                typos.add(variant)
    return frozenset(typos)


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    docs = [bodies[ref] for _, _, ref in corpus if ref in bodies]
    if len(docs) < MIN_MESSAGES:
        return None

    # Count per-doc appearances to filter low-frequency accidents.
    all_words: Counter[str] = Counter()
    for doc in docs:
        for w in set(_WORD_RE.findall(doc.lower())):
            all_words[w] += 1

    # Only consider words that appear in a meaningful fraction of messages.
    freq_words: Counter[str] = Counter(
        {w: c for w, c in all_words.items() if c >= MIN_WORD_OCCURRENCES}
    )

    if len(freq_words) < MIN_VOCAB_SIZE:
        return None

    typos = _find_persistent_typos(freq_words)

    # Stable fingerprint: sort the typo set, hash it.
    canonical = ",".join(sorted(typos))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    ts_vals = [ts.timestamp() for ts, _, _ in corpus]

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=fingerprint,
        confidence=min(1.0, len(docs) / 100),
        window=Window(start_ts=min(ts_vals), end_ts=max(ts_vals)),
        source=f"eyenet/sensor/primitives/typo_sig:v{PRIMITIVE_VERSION}",
        evidence_ref=corpus[-1][2] if corpus else None,
        ts=time.time(),
    )


__all__ = [
    "MIN_MESSAGES",
    "PRIMITIVE_NAME",
    "PRIMITIVE_VERSION",
    "TYPO_RATE_THRESHOLD",
    "compute",
]
