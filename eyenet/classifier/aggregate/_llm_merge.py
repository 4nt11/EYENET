"""Merge the LLM advisory into the verdict — FLAG-ONLY, tier never lowered (§4).

This is the §4 ``if llm.tier > tier: raise_operator_review_flag(llm)`` step,
deferred here from slice 5. Pure and I/O-free: it takes the deterministic
verdict and an advisory outcome and returns a new verdict that differs only in
``llm`` (the attached analysis) and ``review_flags`` — never ``tier``.

Two outcomes:

- :class:`~eyenet.classifier.llm.LlmAdvisory`: the analysis is attached for every
  document (all tiers — the analyst job is universal). A tripwire flag is raised
  ONLY when the model judged the document *more* sensitive than the binding tier
  AND that tier is below CLASSIFIED (nothing is higher to flag). The suggested
  demotion of an over-eager deterministic tier is never acted on automatically —
  that is the catastrophic under-classify direction (§0).
- :class:`~eyenet.classifier.llm.LlmUnavailable`: an informational
  ``LLM_UNAVAILABLE`` flag records that the semantic tripwire did not deploy, so
  a human knows the safety net was absent on this document.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from eyenet.classifier.llm import LlmAdvisory, LlmUnavailable
from eyenet.classifier.ruleset._types import max_tier
from eyenet.contracts.enums import SensitivityTier

from ._types import ReviewFlag, ReviewKind

if TYPE_CHECKING:
    from ._types import ClassificationVerdict

__all__ = ["apply_llm_advisory"]


def _exceeds(suggested: SensitivityTier, tier: SensitivityTier) -> bool:
    """True iff ``suggested`` is strictly higher than ``tier`` (monotone order)."""
    return suggested != tier and max_tier((suggested, tier)) == suggested


def apply_llm_advisory(
    verdict: ClassificationVerdict,
    outcome: LlmAdvisory | LlmUnavailable,
) -> ClassificationVerdict:
    """Attach the advisory and raise any review flag — leaving ``tier`` untouched."""
    if isinstance(outcome, LlmUnavailable):
        flag = ReviewFlag(
            kind=ReviewKind.LLM_UNAVAILABLE,
            detail=f"semantic LLM tripwire did not deploy ({outcome.reason})",
        )
        return replace(verdict, review_flags=(*verdict.review_flags, flag))

    flags = list(verdict.review_flags)
    if verdict.tier is not SensitivityTier.CLASSIFIED and _exceeds(
        outcome.suggested_tier, verdict.tier
    ):
        flags.append(
            ReviewFlag(
                kind=ReviewKind.LLM_HIGHER_TIER,
                detail=(
                    f"LLM judged {outcome.suggested_tier.value} (confidence "
                    f"{outcome.confidence}); deterministic tier {verdict.tier.value} "
                    "unchanged — operator review (§4)"
                ),
                suggested_tier=outcome.suggested_tier,
            )
        )
    return replace(verdict, llm=outcome, review_flags=tuple(flags))
