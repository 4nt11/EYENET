"""Presidio value types: frozen, hashable, redaction purity."""

from __future__ import annotations

import dataclasses

import pytest

from eyenet.classifier.presidio import (
    PiiFinding,
    PresidioMatch,
    PresidioVerdict,
)
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit


def _match() -> PresidioMatch:
    return PresidioMatch(
        entity_type="US_SSN",
        tier_floor=SensitivityTier.CLASSIFIED,
        start=4,
        end=15,
        score=0.95,
        language="en",
        matched_text="123-45-6789",
    )


def test_finding_is_frozen() -> None:
    f = PiiFinding("PERSON", 0, 4, 0.9, "es", "Juan")
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.score = 0.1  # type: ignore[misc]


def test_verdict_is_hashable() -> None:
    verdict = PresidioVerdict(
        tier_floor=SensitivityTier.CLASSIFIED, matches=(_match(),), map_version="v"
    )
    assert hash(verdict)  # tuple-of-frozen matches keeps the verdict hashable


def test_verdict_defaults() -> None:
    verdict = PresidioVerdict(tier_floor=SensitivityTier.NORMAL, matches=(), map_version="v")
    assert verdict.engine == "presidio"
    assert verdict.fail_closed is False


def test_match_redacted_masks_span_keeps_provenance() -> None:
    m = _match()
    red = m.redacted()
    assert "123-45-6789" not in red.matched_text  # raw PII gone
    assert red.matched_text.endswith("6789")  # last-4 retained for review
    # identity / offsets / tier / score / lang preserved
    assert (red.entity_type, red.start, red.end, red.tier_floor, red.score, red.language) == (
        m.entity_type,
        m.start,
        m.end,
        m.tier_floor,
        m.score,
        m.language,
    )
    assert m.matched_text == "123-45-6789"  # original untouched (frozen → copy)


def test_verdict_redacted_masks_all_matches() -> None:
    verdict = PresidioVerdict(
        tier_floor=SensitivityTier.CLASSIFIED, matches=(_match(),), map_version="v"
    )
    red = verdict.redacted()
    assert "123-45-6789" not in red.matches[0].matched_text
    assert verdict.matches[0].matched_text == "123-45-6789"  # original untouched
    assert red.tier_floor is verdict.tier_floor  # only spans change
