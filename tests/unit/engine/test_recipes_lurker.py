"""Unit tests for the lurker_or_observer recipe."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.attribution import ProfileRow
from eyenet.engine.recipes.lurker_or_observer import (
    UNCALIBRATED_MAX_INITIATION_RATE,
    UNCALIBRATED_MIN_OBSERVATION_COUNT,
    LurkerOrObserverRecipe,
)

_UUID = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 1, tzinfo=UTC)


def _profile(init_rate: float | None = None) -> ProfileRow:
    interaction: dict[str, object] = {}
    if init_rate is not None:
        interaction["conversation_initiation_rate"] = {
            "value": init_rate,
            "last_observation_id": str(_UUID),
            "derived_from_observation_count": 50,
        }
    return ProfileRow(
        id=_UUID,
        actor_id=_UUID,
        version=1,
        is_current=True,
        role_signal=None,
        role_confidence=0.0,
        interaction_summary=interaction,
        derived_at=_NOW,
        derived_from_observation_count=50,
    )


_recipe = LurkerOrObserverRecipe()


@pytest.mark.unit
def test_matches_below_threshold() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.02), 50)
    assert result.matches is True
    assert result.confidence > 0.0


@pytest.mark.unit
def test_no_match_above_threshold() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.50), 50)
    assert result.matches is False
    assert result.confidence == 0.0


@pytest.mark.unit
def test_at_threshold_boundary_does_match() -> None:
    # Exactly at threshold → still "≤", so matches
    result = _recipe.evaluate(_profile(init_rate=UNCALIBRATED_MAX_INITIATION_RATE), 50)
    assert result.matches is True


@pytest.mark.unit
def test_missing_slot_returns_no_match() -> None:
    result = _recipe.evaluate(_profile(init_rate=None), 50)
    assert result.matches is False


@pytest.mark.unit
def test_reasoning_carries_calibrated_false() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.01), 50)
    assert result.reasoning.get("calibrated") is False


@pytest.mark.unit
def test_reasoning_contains_threshold() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.01), 50)
    assert "threshold_max_initiation_rate" in result.reasoning


@pytest.mark.unit
def test_low_observation_count_reduces_confidence() -> None:
    high_count = _recipe.evaluate(_profile(init_rate=0.01), UNCALIBRATED_MIN_OBSERVATION_COUNT)
    low_count = _recipe.evaluate(_profile(init_rate=0.01), 1)
    assert low_count.confidence < high_count.confidence
