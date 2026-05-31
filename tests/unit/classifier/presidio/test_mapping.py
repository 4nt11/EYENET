"""map_findings(): deterministic MAX-floor verdict over type + density + confidence."""

from __future__ import annotations

import pytest

from eyenet.classifier.presidio import (
    EntityRule,
    PiiFinding,
    PiiMap,
    map_findings,
)
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit


def _map() -> PiiMap:
    """Small test map: low density cut-offs so clustering is easy to exercise."""
    return PiiMap(
        map_version="test",
        entities={
            "US_SSN": EntityRule(tier_floor=SensitivityTier.CLASSIFIED, min_score=0.4),
            "EMAIL_ADDRESS": EntityRule(tier_floor=SensitivityTier.RESTRICTED, min_score=0.4),
            "PERSON": EntityRule(tier_floor=SensitivityTier.NORMAL, min_score=0.5),
        },
        restricted_at=3,
        classified_at=5,
    )


def _person(start: int, *, score: float = 0.9, language: str = "es") -> PiiFinding:
    return PiiFinding(
        entity_type="PERSON",
        start=start,
        end=start + 4,
        score=score,
        language=language,
        text="Juan",
    )


# ---- core behavior ---------------------------------------------------------


def test_no_findings_is_normal() -> None:
    verdict = map_findings([], _map())
    assert verdict.tier_floor is SensitivityTier.NORMAL
    assert verdict.matches == ()
    assert verdict.engine == "presidio"
    assert verdict.map_version == "test"
    assert verdict.fail_closed is False


def test_single_strong_type_classifies() -> None:
    ssn = PiiFinding("US_SSN", 5, 16, 0.95, "en", "123-45-6789")
    verdict = map_findings([ssn], _map())
    assert verdict.tier_floor is SensitivityTier.CLASSIFIED
    assert [m.entity_type for m in verdict.matches] == ["US_SSN"]
    assert verdict.matches[0].matched_text == "123-45-6789"


def test_subthreshold_known_finding_dropped() -> None:
    # US_SSN below its 0.4 gate is noise — dropped entirely, floor stays NORMAL.
    weak = PiiFinding("US_SSN", 0, 11, 0.2, "en", "123-45-6789")
    verdict = map_findings([weak], _map())
    assert verdict.tier_floor is SensitivityTier.NORMAL
    assert verdict.matches == ()


def _email(start: int, *, score: float = 0.9, language: str = "en") -> PiiFinding:
    return PiiFinding("EMAIL_ADDRESS", start, start + 13, score, language, "a@example.net")


def test_lone_person_stays_normal() -> None:
    # One NER name is low-signal: NORMAL floor, below the density cut-off.
    verdict = map_findings([_person(0)], _map())
    assert verdict.tier_floor is SensitivityTier.NORMAL
    assert len(verdict.matches) == 1


def test_person_cluster_does_not_escalate_by_density() -> None:
    # v2 recalibration: NORMAL-floor names do NOT count toward density (slice-9
    # finding — benign docs are name-dense). A pile of PERSONs stays NORMAL; only
    # a cluster of STRONG identifiers escalates.
    verdict = map_findings([_person(i * 10) for i in range(8)], _map())
    assert verdict.tier_floor is SensitivityTier.NORMAL


def test_strong_id_cluster_escalates_by_density() -> None:
    # In this test map EMAIL_ADDRESS is RESTRICTED-floor (a "strong" type), so a
    # cluster of them counts toward density: restricted_at=3 -> RESTRICTED,
    # classified_at=5 -> CLASSIFIED (each EMAIL already floors RESTRICTED by type;
    # the cluster pushes it to CLASSIFIED).
    assert map_findings([_email(i * 20) for i in range(3)], _map()).tier_floor is (
        SensitivityTier.RESTRICTED
    )
    assert map_findings([_email(i * 20) for i in range(5)], _map()).tier_floor is (
        SensitivityTier.CLASSIFIED
    )


def test_max_over_mixed_types() -> None:
    # PERSON (normal) + EMAIL (restricted in this map), below density -> RESTRICTED
    # via the per-type floor.
    findings = [_person(0), _email(10)]
    assert map_findings(findings, _map()).tier_floor is SensitivityTier.RESTRICTED


def test_unknown_entity_kept_as_provenance_at_normal() -> None:
    # An entity not in the map is never silently dropped (over-keep is §0-safe):
    # kept as a match at a NORMAL floor. NORMAL-floor types (including unknowns)
    # do NOT count toward the strong-identifier density signal (v2).
    unknown = PiiFinding("FOO_TOKEN", 0, 5, 0.99, "en", "XY-99")
    verdict = map_findings([unknown], _map())
    assert verdict.tier_floor is SensitivityTier.NORMAL
    assert [m.entity_type for m in verdict.matches] == ["FOO_TOKEN"]
    assert verdict.matches[0].tier_floor is SensitivityTier.NORMAL


def test_es_en_overlap_is_deduped_for_density() -> None:
    # Both engines report the SAME three EMAILs at the SAME spans (6 findings).
    # Dedup by (start,end,type) -> 3 distinct strong IDs -> RESTRICTED at
    # restricted_at=3, NOT 6 -> CLASSIFIED (double-counting would over-escalate).
    findings = [_email(s, language=lang) for s in (0, 20, 40) for lang in ("es", "en")]
    verdict = map_findings(findings, _map())
    assert verdict.tier_floor is SensitivityTier.RESTRICTED
    assert len(verdict.matches) == 3


def test_dedup_keeps_higher_confidence() -> None:
    low = _person(0, score=0.6, language="en")
    high = _person(0, score=0.95, language="es")
    verdict = map_findings([low, high], _map())
    assert len(verdict.matches) == 1
    assert verdict.matches[0].score == pytest.approx(0.95)
    assert verdict.matches[0].language == "es"


def test_dedup_is_order_independent() -> None:
    # Higher-confidence finding FIRST: the later lower one must not displace it.
    low = _person(0, score=0.6, language="en")
    high = _person(0, score=0.95, language="es")
    verdict = map_findings([high, low], _map())
    assert len(verdict.matches) == 1
    assert verdict.matches[0].score == pytest.approx(0.95)


def test_matches_sorted_by_offset_then_type() -> None:
    findings = [
        PiiFinding("EMAIL_ADDRESS", 30, 45, 0.9, "en", "a@example.net"),
        _person(0),
        _person(10),
    ]
    verdict = map_findings(findings, _map())
    assert [m.start for m in verdict.matches] == sorted(m.start for m in verdict.matches)


def test_determinism_same_findings_same_verdict() -> None:
    findings = [_person(0), PiiFinding("US_SSN", 10, 21, 0.9, "en", "123-45-6789")]
    first = map_findings(findings, _map())
    second = map_findings(list(findings), _map())
    assert first == second  # frozen dataclasses compare structurally
