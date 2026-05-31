"""Value types for the Presidio PII stage — dependency-free, frozen.

Mirrors :mod:`eyenet.classifier.ruleset._types`: the verdict carries the
*provenance* that makes a classification defensible (which PII entity, where, at
what confidence, in which language engine). The tier arithmetic reuses the
ruleset's monotone :func:`max_tier` — there is exactly one tier order in the
codebase and it lives there.

``matched_text`` holds the RAW span (operator-grade evidence). Use
:meth:`PresidioMatch.redacted` / :meth:`PresidioVerdict.redacted` before anything
reaches a log line or a lower-clearance surface; structured logs are NOT
clearance-gated.

A :class:`PiiFinding` is the RAW, pre-decision output of the jailed worker; the
pure mapper turns a list of findings into a :class:`PresidioVerdict`. Splitting
the two keeps the decision logic trivially unit-testable without nsjail.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from eyenet.classifier.ruleset._types import _mask

if TYPE_CHECKING:
    from eyenet.contracts.enums import SensitivityTier


@dataclass(frozen=True, slots=True)
class PiiFinding:
    """One raw entity the jailed worker reported, before any tier decision."""

    entity_type: str  # presidio label: PERSON, US_SSN, IBAN_CODE, EMAIL_ADDRESS, ...
    start: int  # codepoint offset into the analyzed (NFC) text
    end: int
    score: float  # presidio confidence 0..1 — fed into the decision, never binarized away
    language: str  # "es" | "en" — which engine produced it
    text: str  # raw matched span


@dataclass(frozen=True, slots=True)
class PresidioMatch:
    """One finding that survived the confidence gate and counted toward the floor."""

    entity_type: str
    tier_floor: SensitivityTier  # the floor this entity type maps to (NORMAL for NER/unknown)
    start: int
    end: int
    score: float
    language: str
    matched_text: str

    def redacted(self) -> PresidioMatch:
        """Return a copy with ``matched_text`` masked — safe for logs/UI."""
        return replace(self, matched_text=_mask(self.matched_text))


@dataclass(frozen=True, slots=True)
class PresidioVerdict:
    """The Presidio stage's verdict for one document: a tier floor + provenance.

    ``tier_floor`` is the MAX over per-entity-type floors and the density floor,
    or NORMAL when nothing counted. A FLOOR only — the aggregator (a later slice)
    takes the MAX of this against the other deterministic stages.

    ``fail_closed`` is True when the jailed NER pass could not complete (OOM,
    timeout, seccomp kill, missing venv, degraded sandbox). Per CLASSIFIER_PLAN
    §0 that forces ``tier_floor`` to CLASSIFIED: anything we cannot read defaults
    to the highest tier, pending operator review.
    """

    tier_floor: SensitivityTier
    matches: tuple[PresidioMatch, ...]
    map_version: str
    engine: str = "presidio"
    fail_closed: bool = False

    def redacted(self) -> PresidioVerdict:
        """Return a copy with every match's ``matched_text`` masked."""
        return replace(self, matches=tuple(m.redacted() for m in self.matches))


@dataclass(frozen=True, slots=True)
class EntityRule:
    """The decision parameters for one operator-mapped PII entity type."""

    tier_floor: SensitivityTier
    min_score: float  # findings below this confidence are dropped as noise


@dataclass(frozen=True, slots=True)
class PiiMap:
    """An immutable, validated PII-type → tier map ready for :func:`map_findings`.

    ``entities`` holds only the enabled rules (parked ones are dropped at load,
    like the ruleset's disabled rules). ``restricted_at`` / ``classified_at`` are
    the distinct-PII-count density thresholds.
    """

    map_version: str
    entities: dict[str, EntityRule]
    restricted_at: int
    classified_at: int
