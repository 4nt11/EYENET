"""The pure decision heart: raw PII findings + a map -> a tier-floor verdict.

I/O-free and deterministic — no nsjail, no presidio, no spaCy. The same findings
under the same ``map_version`` always yield the same verdict; that
reproducibility is what makes the assigned tier defensible (CLASSIFIER_PLAN §4).

Two signals combine, both monotone-up:

* **per-type floor** — a strong identifier (government ID, IBAN, crypto) raises
  the floor on a single high-confidence hit; NER types (PERSON/ORG/LOCATION) sit
  at NORMAL and escalate only by density.
* **density floor** — a *cluster of strong identifiers* (RESTRICTED+ floor types:
  many SSNs / cards / IBANs — a breach dump) escalates. Names and contact info
  (NORMAL floor) do NOT count: slice-9 calibration proved raw NER density is
  non-discriminative for documents (benign news/blogs are the most entity-dense).

Confidence is fed in, not binarized away: a known-type finding below its
``min_score`` is dropped as noise before it can inflate either signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eyenet.classifier.ruleset._types import max_tier
from eyenet.contracts.enums import SensitivityTier

from ._types import PresidioMatch, PresidioVerdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ._types import PiiFinding, PiiMap

__all__ = ["map_findings"]


def _dedup_and_gate(findings: Sequence[PiiFinding], pii_map: PiiMap) -> list[PiiFinding]:
    """Drop sub-confidence known-type findings, then collapse duplicate spans.

    The es and en engines both run over the same text, so the same entity at the
    same span is reported twice (once per language). Counting both would double
    the density signal, so we keep one finding per ``(start, end, entity_type)``
    — the highest-confidence one, ties broken deterministically by language. A
    finding whose entity type is in the map but scores below its ``min_score`` is
    noise and is dropped entirely (it never reaches provenance or density). An
    *unknown* entity type (not in the map) has no gate — it is always kept, so we
    never silently drop a signal (over-keep is the §0-safe direction).
    """
    best: dict[tuple[int, int, str], PiiFinding] = {}
    for f in findings:
        rule = pii_map.entities.get(f.entity_type)
        if rule is not None and f.score < rule.min_score:
            continue  # known type below its confidence floor — noise
        key = (f.start, f.end, f.entity_type)
        current = best.get(key)
        if (
            current is None
            or f.score > current.score
            or (f.score == current.score and f.language < current.language)
        ):
            best[key] = f
    return list(best.values())


def map_findings(findings: Sequence[PiiFinding], pii_map: PiiMap) -> PresidioVerdict:
    """Map raw worker findings to a tier-floor verdict with per-match provenance.

    The floor is ``MAX(per-type floors, density floor)``; NORMAL when nothing
    counted. Matches are sorted by ``(start, entity_type)`` for a stable,
    reproducible order. Unknown entity types are kept at a NORMAL floor for
    provenance and still count toward density (they are real PII spans).
    """
    survivors = _dedup_and_gate(findings, pii_map)

    matches: list[PresidioMatch] = []
    type_floors: list[SensitivityTier] = []
    for f in survivors:
        rule = pii_map.entities.get(f.entity_type)
        tier = rule.tier_floor if rule is not None else SensitivityTier.NORMAL
        type_floors.append(tier)
        matches.append(
            PresidioMatch(
                entity_type=f.entity_type,
                tier_floor=tier,
                start=f.start,
                end=f.end,
                score=f.score,
                language=f.language,
                matched_text=f.text,
            )
        )

    # Density counts ONLY "real identifier" findings — those whose mapped floor is
    # RESTRICTED or higher. Names, contact info (email/phone/location/IP), and
    # unknown types sit at NORMAL and DO NOT inflate density. Slice-9 calibration
    # proved raw NER density is non-discriminative for documents: a benign news
    # article naming 40 people/orgs/locations is not sensitive, and counting those
    # collapsed ~59% of real documents upward. A *cluster of strong identifiers*
    # (many SSNs / cards / IBANs — a breach dump) is the genuine density signal.
    # This also neutralizes parked types (DATE_TIME/URL), which were previously
    # kept-as-unknown and silently counted toward density.
    strong = sum(1 for t in type_floors if t is not SensitivityTier.NORMAL)
    density_floor = SensitivityTier.NORMAL
    if strong >= pii_map.classified_at:
        density_floor = SensitivityTier.CLASSIFIED
    elif strong >= pii_map.restricted_at:
        density_floor = SensitivityTier.RESTRICTED

    floor = max_tier([*type_floors, density_floor])
    matches.sort(key=lambda m: (m.start, m.entity_type))
    return PresidioVerdict(
        tier_floor=floor,
        matches=tuple(matches),
        map_version=pii_map.map_version,
    )
