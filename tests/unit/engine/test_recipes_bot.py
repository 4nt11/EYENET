"""Unit tests for the bot_or_automated_poster recipe (M5-calibrated axes)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.attribution import ProfileRow
from eyenet.engine.recipes.bot_or_automated_poster import (
    LENGTH_VARIANCE_TIGHT_VALUE,
    MIN_INITIATION_RATE,
    BotOrAutomatedPosterRecipe,
)

_UUID = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 1, tzinfo=UTC)


def _profile(
    init_rate: float | None = None,
    length_variance: str | None = None,
) -> ProfileRow:
    interaction: dict[str, object] = {}
    stylometric: dict[str, object] = {}
    if init_rate is not None:
        interaction["conversation_initiation_rate"] = {
            "value": init_rate,
            "last_observation_id": str(_UUID),
            "derived_from_observation_count": 50,
        }
    if length_variance is not None:
        stylometric["message_length_variance_class"] = {
            "value": length_variance,
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
        stylometric_summary=stylometric,
        derived_at=_NOW,
        derived_from_observation_count=50,
    )


_recipe = BotOrAutomatedPosterRecipe()


@pytest.mark.unit
def test_matches_bot_pattern() -> None:
    # High initiation + tight length variance → bot
    result = _recipe.evaluate(_profile(init_rate=0.98, length_variance="tight"), 50)
    assert result.matches is True
    assert result.confidence > 0.0


@pytest.mark.unit
def test_no_match_low_initiation() -> None:
    # Tight length but low init → not a bot
    result = _recipe.evaluate(_profile(init_rate=0.20, length_variance="tight"), 50)
    assert result.matches is False


@pytest.mark.unit
def test_no_match_varied_length() -> None:
    # High initiation but human-like length variance → not a bot
    result = _recipe.evaluate(_profile(init_rate=0.98, length_variance="varied"), 50)
    assert result.matches is False


@pytest.mark.unit
def test_no_match_bimodal_length() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.98, length_variance="bimodal"), 50)
    assert result.matches is False


@pytest.mark.unit
def test_missing_slots_no_match() -> None:
    result = _recipe.evaluate(_profile(), 50)
    assert result.matches is False


@pytest.mark.unit
def test_missing_length_variance_no_match() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.99, length_variance=None), 50)
    assert result.matches is False


@pytest.mark.unit
def test_reasoning_calibrated_true() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.98, length_variance="tight"), 50)
    assert result.reasoning.get("calibrated") is True
    assert result.reasoning.get("calibration_corpus") == "rutify-full-2026-05-02"


@pytest.mark.unit
def test_at_both_thresholds_matches() -> None:
    # Exactly at boundary
    result = _recipe.evaluate(
        _profile(
            init_rate=MIN_INITIATION_RATE,
            length_variance=LENGTH_VARIANCE_TIGHT_VALUE,
        ),
        50,
    )
    assert result.matches is True


@pytest.mark.unit
def test_below_init_threshold_no_match() -> None:
    # 0.949 is just below the 0.95 threshold
    result = _recipe.evaluate(_profile(init_rate=0.949, length_variance="tight"), 50)
    assert result.matches is False
