"""Value types for the classifier aggregator — dependency-free, frozen.

Mirrors :mod:`eyenet.classifier.ruleset._types` and
:mod:`eyenet.classifier.presidio._types`: the verdict carries the *provenance*
that makes the final classification defensible — which stage produced which
floor, at which version, and why. The tier arithmetic reuses the ruleset's
monotone :func:`max_tier`; there is exactly one tier order in the codebase.

This module is pure data: no nsjail, no storage, no LLM. The aggregator
(:mod:`._aggregate`) builds a :class:`ClassificationVerdict` from the three
stage outputs; the audit payload builder (:mod:`._audit`) serializes it.
``review_flags`` are redaction-safe by construction (no raw spans); the
sub-verdicts retain raw matched spans as operator-grade evidence — call
:meth:`ClassificationVerdict.redacted` before anything reaches a log line.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eyenet.classifier.llm import LlmAdvisory
    from eyenet.classifier.presidio._types import PresidioVerdict
    from eyenet.classifier.ruleset._types import RegexVerdict
    from eyenet.contracts.enums import SensitivityTier


class ReviewKind(StrEnum):
    """Why an operator-review flag was raised. The tier is NEVER changed by it."""

    POSSIBLE_OVER_CLASSIFICATION = "possible_over_classification"  # counter-signal co-occurrence
    LLM_HIGHER_TIER = "llm_higher_tier"  # the advisory LLM judged it more sensitive
    LLM_UNAVAILABLE = "llm_unavailable"  # the semantic tripwire could not deploy on this doc


@dataclass(frozen=True, slots=True)
class ReviewFlag:
    """A non-binding operator-review signal. NEVER mutates the tier (§0/§4)."""

    kind: ReviewKind
    detail: str  # human-readable, redaction-safe — carries no raw spans
    suggested_tier: SensitivityTier | None = None  # what review MIGHT change it to


@dataclass(frozen=True, slots=True)
class StageProvenance:
    """One pipeline stage's contribution to the verdict — persisted as evidence."""

    stage: str  # "extraction" | "regex" | "presidio"
    tier_floor: SensitivityTier
    version: str  # ruleset_version | map_version | extraction method or FailReason
    fail_closed: bool = False
    detail: str = ""  # FailReason detail / extraction flags; "" for the deterministic stages


@dataclass(frozen=True, slots=True)
class ClassificationVerdict:
    """The aggregated, court-defensible classification for one document.

    ``tier`` is the BINDING ``MAX`` of the three deterministic floors
    (extraction-failure, regex, presidio). It is never lowered: counter-signals
    and the advisory LLM raise ``review_flags`` instead (CLASSIFIER_PLAN §0/§4).
    ``consult_llm`` is the §4 short-circuit gate — True only when the tier is
    below CLASSIFIED and nothing failed closed. ``fail_closed`` is True when any
    stage failed closed and forced the tier to CLASSIFIED. ``llm`` is the
    advisory outcome once the (flag-only) LLM stage has run — ``None`` until then;
    it never altered ``tier``.
    """

    tier: SensitivityTier
    provenance: tuple[StageProvenance, ...]
    regex: RegexVerdict
    presidio: PresidioVerdict
    review_flags: tuple[ReviewFlag, ...] = ()
    consult_llm: bool = False
    fail_closed: bool = False
    llm: LlmAdvisory | None = None

    def redacted(self) -> ClassificationVerdict:
        """Return a copy with raw spans + LLM free-text masked — safe for logs."""
        return replace(
            self,
            regex=self.regex.redacted(),
            presidio=self.presidio.redacted(),
            llm=self.llm.redacted() if self.llm is not None else None,
        )
