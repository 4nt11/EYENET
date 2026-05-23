"""Unit tests for the bot_or_automated_poster recipe."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.attribution import ProfileRow
from eyenet.engine.recipes.bot_or_automated_poster import (
    UNCALIBRATED_MAX_MATTR,
    UNCALIBRATED_MIN_INITIATION_RATE,
    BotOrAutomatedPosterRecipe,
)

_UUID = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 1, tzinfo=UTC)


def _profile(init_rate: float | None = None, mattr: float | None = None) -> ProfileRow:
    interaction: dict[str, object] = {}
    lexical: dict[str, object] = {}
    if init_rate is not None:
        interaction["conversation_initiation_rate"] = {
            "value": init_rate,
            "last_observation_id": str(_UUID),
            "derived_from_observation_count": 50,
        }
    if mattr is not None:
        lexical["mattr"] = {
            "value": mattr,
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
        lexical_summary=lexical,
        derived_at=_NOW,
        derived_from_observation_count=50,
    )


_recipe = BotOrAutomatedPosterRecipe()


@pytest.mark.unit
def test_matches_bot_pattern() -> None:
    # High initiation + low MATTR → bot
    result = _recipe.evaluate(_profile(init_rate=0.98, mattr=0.40), 50)
    assert result.matches is True
    assert result.confidence > 0.0


@pytest.mark.unit
def test_no_match_low_initiation() -> None:
    # High MATTR + low init → not a bot
    result = _recipe.evaluate(_profile(init_rate=0.20, mattr=0.40), 50)
    assert result.matches is False


@pytest.mark.unit
def test_no_match_high_mattr() -> None:
    # High initiation but rich vocabulary → not a bot
    result = _recipe.evaluate(_profile(init_rate=0.98, mattr=0.90), 50)
    assert result.matches is False


@pytest.mark.unit
def test_missing_slots_no_match() -> None:
    # Neither slot populated
    result = _recipe.evaluate(_profile(), 50)
    assert result.matches is False


@pytest.mark.unit
def test_missing_mattr_no_match() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.99, mattr=None), 50)
    assert result.matches is False


@pytest.mark.unit
def test_reasoning_calibrated_false() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.98, mattr=0.40), 50)
    assert result.reasoning.get("calibrated") is False


@pytest.mark.unit
def test_reasoning_note_mentions_future_primitives() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.98, mattr=0.40), 50)
    note = str(result.reasoning.get("note", ""))
    assert "M5" in note or "punctuation" in note


@pytest.mark.unit
def test_at_both_thresholds_matches() -> None:
    # Exactly at both boundaries
    result = _recipe.evaluate(
        _profile(
            init_rate=UNCALIBRATED_MIN_INITIATION_RATE,
            mattr=UNCALIBRATED_MAX_MATTR,
        ),
        50,
    )
    assert result.matches is True
