"""Stylometric primitive: ``stylometric.pos_ngram_signature``.

64-bit simhash over UPOS bigram frequencies for one actor's corpus.
Captures the actor's syntactic skeleton independent of vocabulary — an
author can change every word and still retain the same POS-bigram
fingerprint.

The simhash features are POS bigrams keyed ``f"{prev_pos}_{curr_pos}"``;
weights are raw counts. Sentence boundaries are NOT bigram breaks (the
kernel runs with the parser disabled and does not segment), but document
boundaries ARE: a bigram never crosses two messages.

Source label per BEHAVE-TEXT 0.1.3 spec: the tagger, language model, and
n-value are declared in the suffix. Example:
``…#spacy-es_core_news_sm-bi#es``. The trailing ``#es`` is consumed by
the slot_mapper's ``_LANGUAGE_SUFFIX_PRIMITIVES`` path to drive per-
language threshold lookup in the Linker.
"""

from __future__ import annotations

import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._locale_morph_kernel import (
    KERNEL_VERSION_TAG,
    MODEL_NAME,
    compute_morph_analysis,
    evidence_ref_for,
)
from ._locale_rules import detect_language, get_ruleset
from ._simhash import simhash64

PRIMITIVE_NAME: str = "stylometric.pos_ngram_signature"
PRIMITIVE_VERSION: str = "0.1"
TAGGER_TAG: str = f"spacy-{MODEL_NAME}-bi"

# Below this token count the POS-bigram simhash is too noisy to be useful
# downstream — function_word_distribution_top50 uses a similar floor.
MIN_TOKENS: int = 200

# Tokenizer for the light language-gate over raw bodies. The kernel uses
# spaCy itself for tokenization downstream, but the gate has to run
# before we spin up the (potentially-downloading) model.
import re  # noqa: E402  — sole user of re in this module

_TOKENIZE = re.compile(r"[a-záéíóúüñàèìòùâêîôûäëïöü']+", re.IGNORECASE)


def _gate_tokens(bodies: list[str]) -> list[str]:
    bag: list[str] = []
    for body in bodies:
        bag.extend(m.group(0).lower() for m in _TOKENIZE.finditer(body))
    return bag


def compute(
    *,
    corpus: list[tuple[datetime, UUID, str]],
    bodies: dict[str, str],
) -> Observation | None:
    """Compute the POS-bigram simhash for one actor's corpus.

    Returns ``None`` when:
      * the corpus has no message bodies in ``bodies`` (every fetch missed)
      * the body bag fails the Spanish language gate (only Spanish ships
        in M6.5; other languages will register their own ruleset later)
      * the kernel produced fewer than :data:`MIN_TOKENS` tagged tokens
    """
    bodies_list = [bodies[ref] for _, _, ref in corpus if ref in bodies]
    if not bodies_list:
        return None

    language = detect_language(_gate_tokens(bodies_list))
    if language is None:
        return None
    ruleset = get_ruleset(language)
    if ruleset is None:
        return None

    analysis = compute_morph_analysis(corpus=corpus, bodies=bodies, ruleset=ruleset)
    if analysis is None or analysis.total_tokens < MIN_TOKENS:
        return None

    features: dict[str, float] = {
        f"{prev}_{curr}": float(count) for (prev, curr), count in analysis.pos_bigrams.items()
    }
    if not features:
        return None
    fingerprint = simhash64(features)

    source = (
        f"eyenet/sensor/primitives/pos-ngram-signature:v{PRIMITIVE_VERSION}"
        f"#{KERNEL_VERSION_TAG}"
        f"#{TAGGER_TAG}"
        f"#{language}"
    )

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=fingerprint,
        # Confidence scales with corpus volume — caps at 1.0 around
        # 2000 tokens. Below MIN_TOKENS we never reach this branch.
        confidence=min(1.0, analysis.total_tokens / 2000.0),
        window=Window(start_ts=analysis.window_start_ts, end_ts=analysis.window_end_ts),
        source=source,
        evidence_ref=evidence_ref_for(corpus, bodies),
        ts=time.time(),
    )


__all__ = [
    "MIN_TOKENS",
    "PRIMITIVE_NAME",
    "PRIMITIVE_VERSION",
    "TAGGER_TAG",
    "compute",
]
