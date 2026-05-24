"""VerifierThresholds.for_verifier semantics — language gating + None disable."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from eyenet.cli.config import VerifierThresholds


@pytest.mark.unit
def test_blind_default_returned_when_language_missing() -> None:
    t = VerifierThresholds()
    assert t.for_verifier("general_impostors", None) == pytest.approx(0.60)


@pytest.mark.unit
def test_per_language_override_wins_over_blind() -> None:
    t = VerifierThresholds(general_impostors_per_lang={"en": 0.75})
    assert t.for_verifier("general_impostors", "en") == pytest.approx(0.75)
    assert t.for_verifier("general_impostors", "es") == pytest.approx(0.60)


@pytest.mark.unit
def test_none_in_per_lang_disables_verifier() -> None:
    t = VerifierThresholds(compression_distance_per_lang={"es": None})
    assert t.for_verifier("compression_distance", "es") is None
    # English is not in the dict — falls back to blind default
    assert t.for_verifier("compression_distance", "en") == pytest.approx(0.55)


@pytest.mark.unit
def test_unknown_verifier_returns_fallback() -> None:
    t = VerifierThresholds()
    # getattr fallback path — non-registered verifier name returns the 0.5 default
    assert t.for_verifier("nonexistent_verifier", None) == pytest.approx(0.5)


@pytest.mark.unit
def test_composite_floor_bounded() -> None:
    t = VerifierThresholds(composite_floor=0.85)
    assert t.composite_floor == pytest.approx(0.85)
    with pytest.raises(ValidationError, match="composite_floor"):
        VerifierThresholds(composite_floor=1.5)
