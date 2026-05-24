"""Lexical primitive: ``lexical.evaluative_morphology_density``.

Density of evaluative-morphology tokens (diminutives, augmentatives,
pejoratives, intensives) relative to the actor's NOUN/ADJ token count.
The choice of denominator — NOUN/ADJ rather than all tokens — keeps the
metric on a comparable scale across actors with different POS mixes
(verb-heavy vs noun-heavy corpora).

Per BEHAVE-TEXT 0.1.3 spec the value range is ``[0.0, 1.0]``. We clamp
defensively: floating-point rounding on small denominators should not
produce a 1.000001 that fails registry validation.

Source label suffix per spec: ``…#eval-morph-es-v1``. The Spanish
morpheme set lives in ``_locale_rules/es.py``; bumping the ``v1`` tag is
the operator-visible signal that the rule pack changed.

Not currently in ``_LANGUAGE_SUFFIX_PRIMITIVES`` (the slot is numeric;
the Linker does not branch on language for it), but the ``#es`` suffix
is still appended for parity with the other two M6.5 primitives.
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

PRIMITIVE_NAME: str = "lexical.evaluative_morphology_density"
PRIMITIVE_VERSION: str = "0.1"
RULESET_TAG: str = "eval-morph-es-v1"

# Minimum NOUN/ADJ count required before the density is statistically
# meaningful. Below this the metric swings wildly on a single token.
MIN_TARGET_TOKENS: int = 50

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
    """Compute evaluative-morphology density for one actor's corpus.

    Returns ``None`` when:
      * the corpus has no message bodies in ``bodies``
      * the body bag fails the Spanish language gate
      * the kernel produced fewer than :data:`MIN_TARGET_TOKENS` NOUN/ADJ
        tokens (density is too noisy to emit)
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
    if analysis is None or analysis.total_evaluative_target_tokens < MIN_TARGET_TOKENS:
        return None

    eval_hits = sum(analysis.evaluative_counts.values())
    density = min(1.0, eval_hits / analysis.total_evaluative_target_tokens)

    source = (
        f"eyenet/sensor/primitives/evaluative-morphology-density:v{PRIMITIVE_VERSION}"
        f"#{KERNEL_VERSION_TAG}"
        f"#{RULESET_TAG}"
        f"#{language}"
    )

    return Observation(
        primitive=PRIMITIVE_NAME,
        value=density,
        confidence=min(1.0, analysis.total_evaluative_target_tokens / 500.0),
        window=Window(start_ts=analysis.window_start_ts, end_ts=analysis.window_end_ts),
        source=source,
        evidence_ref=evidence_ref_for(corpus, bodies),
        ts=time.time(),
    )


__all__ = [
    "MIN_TARGET_TOKENS",
    "PRIMITIVE_NAME",
    "PRIMITIVE_VERSION",
    "RULESET_TAG",
    "compute",
]
