"""Bag-of-features extractors for stylometric verifiers (M8).

Shared by ``general_impostors``; future verifiers (e.g. cosine on hand-
engineered features) reuse the same vocabularies. Pure functions; no
external state.

Why a private module instead of importing from ``decnet_behave_text``:
BEHAVE-TEXT primitives are sealed (simhash projections, mostly). The
verifier needs the underlying raw COUNTS / DISTRIBUTIONS for impostor-pool
similarity calculations — different shape, different audience.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

# Short, durable Spanish function-word set. Mirrors the spirit of the
# BEHAVE-TEXT ``function_word_distribution_top50`` primitive but exposed as
# the raw vocabulary the verifier counts on. Kept small (~50) on purpose:
# the GI verifier benefits from a low-dimensional, high-density feature
# space when the per-actor corpus is short chat.
_FUNCTION_WORDS_ES: tuple[str, ...] = (
    "de",
    "la",
    "que",
    "el",
    "en",
    "y",
    "a",
    "los",
    "se",
    "del",
    "las",
    "un",
    "por",
    "con",
    "no",
    "una",
    "su",
    "para",
    "es",
    "al",
    "lo",
    "como",
    "mas",
    "pero",
    "sus",
    "le",
    "ya",
    "o",
    "este",
    "si",
    "porque",
    "esta",
    "entre",
    "cuando",
    "muy",
    "sin",
    "sobre",
    "tambien",
    "me",
    "hasta",
    "hay",
    "donde",
    "han",
    "quien",
    "estan",
    "fue",
    "mi",
    "todo",
    "yo",
    "te",
)

# English mirror set — enables M8 verifiers to operate on English-language
# corpora without a fresh vocabulary build. Same shape, same size.
_FUNCTION_WORDS_EN: tuple[str, ...] = (
    "the",
    "of",
    "and",
    "to",
    "a",
    "in",
    "is",
    "it",
    "you",
    "that",
    "he",
    "was",
    "for",
    "on",
    "are",
    "with",
    "as",
    "i",
    "his",
    "they",
    "be",
    "at",
    "one",
    "have",
    "this",
    "from",
    "or",
    "had",
    "by",
    "hot",
    "but",
    "some",
    "what",
    "there",
    "we",
    "can",
    "out",
    "other",
    "were",
    "all",
    "your",
    "when",
    "up",
    "use",
    "word",
    "how",
    "said",
    "an",
    "each",
    "she",
)

_TOKEN_RE = re.compile(r"\b[\w']+\b", re.UNICODE)


def _vocab_for(language: str | None) -> tuple[str, ...]:
    if language == "en":
        return _FUNCTION_WORDS_EN
    # Default Spanish — EYENET's calibrated language. Unknown languages fall
    # back here on purpose; if the verifier needs strict per-language
    # behavior it sets ``requires_language=True`` and gates upstream.
    return _FUNCTION_WORDS_ES


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens. Stable across runs."""
    return _TOKEN_RE.findall(text.lower())


def function_word_vector(
    corpus: Iterable[str],
    *,
    language: str | None = None,
) -> dict[str, float]:
    """Relative-frequency distribution over the language's function-word set.

    Vector keys are the function-word vocabulary; values sum to 1.0 when at
    least one function-word token appears in the corpus, otherwise the
    dict is empty (caller treats it as zero-norm).
    """
    vocab = _vocab_for(language)
    vocab_set = frozenset(vocab)
    counts: Counter[str] = Counter()
    for body in corpus:
        for tok in tokenize(body):
            if tok in vocab_set:
                counts[tok] += 1
    total = sum(counts.values())
    if total == 0:
        return {}
    return {word: counts[word] / total for word in vocab if counts[word] > 0}


def char_trigrams(text: str) -> Counter[str]:
    """Character trigram counts. Language-agnostic, robust on short text."""
    counts: Counter[str] = Counter()
    norm = text.lower()
    for i in range(len(norm) - 2):
        counts[norm[i : i + 3]] += 1
    return counts


def char_trigram_vector(corpus: Iterable[str]) -> dict[str, float]:
    """Relative-frequency distribution over character trigrams across the corpus."""
    counts: Counter[str] = Counter()
    for body in corpus:
        counts.update(char_trigrams(body))
    total = sum(counts.values())
    if total == 0:
        return {}
    return {tri: c / total for tri, c in counts.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Standard cosine on sparse dict vectors. Returns 0.0 on either empty side."""
    if not a or not b:
        return 0.0
    # Iterate over the smaller side for the dot product.
    if len(a) > len(b):
        a, b = b, a
    dot = sum(va * b.get(k, 0.0) for k, va in a.items())
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


__all__ = [
    "char_trigram_vector",
    "char_trigrams",
    "cosine",
    "function_word_vector",
    "tokenize",
]
