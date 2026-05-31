"""Regex ruleset engine — the deterministic, court-defensible classifier spine.

Stage 1 of the classifier pipeline (CLASSIFIER_PLAN §1). Matches versioned,
operator-editable regex rules over extracted text and returns a sensitivity-tier
FLOOR with per-match provenance. Deterministic and reproducible: the same bytes
under the same ``ruleset_version`` always yield the same verdict.

Named ``ruleset`` (not ``regex``) on purpose — a ``regex`` package would shadow
the PyPI ``regex`` library. The engine itself is google-re2 (linear-time,
ReDoS-immune by construction).

Typical use::

    ruleset = load_ruleset()                 # bundled default, or the env override
    verdict = classify(extract_result.text, ruleset)
    floor = verdict.tier_floor               # a FLOOR; the aggregator takes the MAX

This stage decides a floor only; binding it to a final tier (MAX against the
other stages, the LLM short-circuit, persistence, audit) belongs to later slices.
"""

from __future__ import annotations

from ._engine import classify
from ._loader import RULESET_ENV, load_ruleset
from ._types import CompiledRule, CompiledRuleset, RegexVerdict, RuleMatch, max_tier

__all__ = [
    "RULESET_ENV",
    "CompiledRule",
    "CompiledRuleset",
    "RegexVerdict",
    "RuleMatch",
    "classify",
    "load_ruleset",
    "max_tier",
]
