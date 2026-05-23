"""Stylometric primitive: function_word_distribution_top50.

64-bit simhash over the relative-frequency vector of the top-50 function words.
Supports English and Spanish; language is chosen by majority vote over the corpus
window using overlap with each word list. Tie → English.

Per BEHAVE-TEXT primitives.py: EMPIRICALLY DOMAIN-FLAWED for Spanish chat corpora
in isolation. Kept for calibration grids and composition with char-ngram.
Weight low until paired with character_ngram_simhash + distinctive_vocabulary_signature.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._simhash import simhash64

PRIMITIVE_NAME = "stylometric.function_word_distribution_top50"
PRIMITIVE_VERSION = "0.2"

MIN_MESSAGES = 30
MIN_TOKENS = 500

# Top-50 English function words (Mosteller-Wallace subset)
FUNCTION_WORDS_EN: tuple[str, ...] = (
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
    "at",
    "be",
    "this",
    "have",
    "from",
    "or",
    "one",
    "had",
    "by",
    "not",
    "but",
    "what",
    "all",
    "were",
    "we",
    "when",
    "your",
    "can",
    "said",
    "there",
    "use",
    "an",
    "each",
    "which",
    "she",
    "do",
    "how",
    "their",
    "if",
    "will",
    "up",
    "other",
    "about",
)

# Top-50 Spanish function words
FUNCTION_WORDS_ES: tuple[str, ...] = (
    "de",
    "la",
    "que",
    "el",
    "en",
    "y",
    "a",
    "los",
    "del",
    "se",
    "las",
    "un",
    "por",
    "con",
    "una",
    "su",
    "para",
    "es",
    "al",
    "lo",
    "como",
    "más",
    "pero",
    "sus",
    "le",
    "ya",
    "o",
    "fue",
    "este",
    "ha",
    "sí",
    "porque",
    "esta",
    "entre",
    "cuando",
    "muy",
    "sin",
    "sobre",
    "ser",
    "tiene",
    "también",
    "me",
    "hasta",
    "hay",
    "donde",
    "han",
    "quien",
    "están",
    "estado",
    "desde",
)

_TOKENIZE = re.compile(r"[a-záéíóúüñàèìòùâêîôûäëïöü']+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKENIZE.finditer(text)]


def _detect_lang(token_lists: list[list[str]]) -> str:
    """Return 'en' or 'es' based on majority function-word overlap."""
    en_set = set(FUNCTION_WORDS_EN)
    es_set = set(FUNCTION_WORDS_ES)
    en_score = es_score = 0
    for tokens in token_lists:
        token_set = set(tokens)
        en_score += len(token_set & en_set)
        es_score += len(token_set & es_set)
    return "es" if es_score > en_score else "en"


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    """Compute the function-word simhash.

    `corpus`  — [(ts, msg_id, evidence_ref), …] from CorpusStore.iter_since
    `bodies`  — evidence_ref → plaintext body
    Returns None if corpus does not meet the minimum window.
    """

    bodies_list = [bodies[ref] for _, _, ref in corpus if ref in bodies]
    if not bodies_list:
        return None

    token_lists = [_tokens(b) for b in bodies_list]
    total_tokens = sum(len(t) for t in token_lists)

    if len(bodies_list) < MIN_MESSAGES and total_tokens < MIN_TOKENS:
        return None

    lang = _detect_lang(token_lists)
    word_list = FUNCTION_WORDS_ES if lang == "es" else FUNCTION_WORDS_EN
    fw_set = set(word_list)

    freq: dict[str, int] = dict.fromkeys(word_list, 0)
    total = 0
    for tokens in token_lists:
        for t in tokens:
            if t in fw_set:
                freq[t] += 1
                total += 1

    if total == 0:
        return None

    rel_freq = {w: freq[w] / total for w in word_list}
    fingerprint = simhash64(rel_freq)

    ts_vals = [ts.timestamp() for ts, _, _ in corpus]
    window = Window(start_ts=min(ts_vals), end_ts=max(ts_vals))

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=fingerprint,
        confidence=min(1.0, total_tokens / 2000),
        window=window,
        source=f"eyenet/sensor/primitives/fnwd-top50:v{PRIMITIVE_VERSION}#{lang}",
        evidence_ref=corpus[-1][2] if corpus else None,
        ts=time.time(),
    )


__all__ = ["MIN_MESSAGES", "MIN_TOKENS", "PRIMITIVE_NAME", "PRIMITIVE_VERSION", "compute"]
