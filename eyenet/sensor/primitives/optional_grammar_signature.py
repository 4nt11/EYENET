"""Lexical primitive: ``lexical.optional_grammar_signature``.

64-bit simhash over the actor's frequency at Spanish optional-grammar
choice points: compound past auxiliaries, subjunctive verb forms, clitic
pronoun bucket preference (le/la/lo families), and relative pronoun
choice (que/cual/quien). See ``_locale_rules/es.py`` for the rule pack.

Per the BEHAVE-TEXT 0.1.3 spec note, this primitive requires sufficient
corpus volume for stable probability estimates — thin corpora produce
noisy hashes. We gate on :data:`MIN_TOKENS` (kernel-counted, not gate-
counted) before emitting.

Source label suffix per spec: ``…#optgrammar-es-v1#es``. The trailing
``#es`` participates in the slot_mapper's
``_LANGUAGE_SUFFIX_PRIMITIVES`` parse path so the Linker can resolve a
per-language Hamming threshold.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from uuid import UUID

from behave_text.spec import Observation, Window

from ._locale_morph_kernel import (
    KERNEL_VERSION_TAG,
    compute_morph_analysis,
    evidence_ref_for,
)
from ._locale_rules import detect_language, get_ruleset
from ._simhash import simhash64

PRIMITIVE_NAME: str = "lexical.optional_grammar_signature"
PRIMITIVE_VERSION: str = "0.1"
RULESET_TAG: str = "optgrammar-es-v1"

MIN_TOKENS: int = 200

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
    """Compute the optional-grammar simhash for one actor's corpus.

    Returns ``None`` when the corpus is too small, fails the language
    gate, or contains no choice-point hits at all (the simhash of an
    empty feature vector is all-zeros and would falsely collide with
    every other empty-vector actor).
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
    if not analysis.optional_grammar_counts:
        return None

    features: dict[str, float] = {
        bucket: float(count) for bucket, count in analysis.optional_grammar_counts.items()
    }
    fingerprint = simhash64(features)

    total_hits = sum(analysis.optional_grammar_counts.values())

    source = (
        f"eyenet/sensor/primitives/optional-grammar-signature:v{PRIMITIVE_VERSION}"
        f"#{KERNEL_VERSION_TAG}"
        f"#{RULESET_TAG}"
        f"#{language}"
    )

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=fingerprint,
        # Confidence is a function of total choice-point hits — the
        # simhash is only stable once enough buckets fired.
        confidence=min(1.0, total_hits / 200.0),
        window=Window(start_ts=analysis.window_start_ts, end_ts=analysis.window_end_ts),
        source=source,
        evidence_ref=evidence_ref_for(corpus, bodies),
        ts=time.time(),
    )


__all__ = [
    "MIN_TOKENS",
    "PRIMITIVE_NAME",
    "PRIMITIVE_VERSION",
    "RULESET_TAG",
    "compute",
]
