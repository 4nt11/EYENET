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


def _couple_over_classification(
    flags: list[ReviewFlag], suggested: SensitivityTier
) -> list[ReviewFlag]:
    """Let the LLM corroborate or suppress a possible-over-classification flag (slice 9).

    The deterministic counter-signal stage may flag a tier as a demotion CANDIDATE
    (an FP-prone marking co-occurring with a counter-signal). The advisory LLM has
    now also read the document, so it gets a vote on whether that demotion looks
    right — but ONLY over whether the human-facing *suggestion* surfaces; the tier
    is never moved (§0):

    - LLM judges NORMAL  → it agrees the marking is a false positive → mark the
      flag ``corroborated`` (a stronger demotion signal for the operator).
    - LLM judges > NORMAL → it disagrees → DROP the over-classification flag; the
      tier stays where the deterministic floors put it (the safe direction).
    """
    out: list[ReviewFlag] = []
    for flag in flags:
        if flag.kind is not ReviewKind.POSSIBLE_OVER_CLASSIFICATION:
            out.append(flag)
            continue
        if suggested is SensitivityTier.NORMAL:
            out.append(replace(flag, corroborated=True))
        # else: LLM judged it sensitive — suppress the demotion suggestion (drop).
    return out


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
        # The LLM did not deploy → no opinion on the over-classification flag; it
        # is left independent (untouched).
        return replace(verdict, review_flags=(*verdict.review_flags, flag))

    # The LLM ran and produced a tier opinion → corroborate/suppress any pending
    # over-classification flag before adding the tripwire flag (slice 9).
    flags = _couple_over_classification(list(verdict.review_flags), outcome.suggested_tier)
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
