"""Unit tests for recipe registry and base helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.attribution import ProfileRow
from eyenet.engine.recipes import REGISTRY, pick_winner
from eyenet.engine.recipes._base import get_slot_value, slots_present

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


@pytest.mark.unit
def test_registry_has_m5_recipes() -> None:
    names = {r.name for r in REGISTRY}
    assert "lurker_or_observer" in names
    assert "bot_or_automated_poster" in names
    assert "chatty_member" in names


@pytest.mark.unit
def test_pick_winner_returns_none_when_no_slots() -> None:
    profile = _profile()
    assert pick_winner(profile, 0) is None


@pytest.mark.unit
def test_pick_winner_returns_lurker_signal() -> None:
    profile = _profile(init_rate=0.02)
    result = pick_winner(profile, 50)
    assert result is not None
    signal, confidence = result
    assert signal == "lurker_or_observer"
    assert confidence > 0.0


@pytest.mark.unit
def test_pick_winner_returns_bot_signal() -> None:
    profile = _profile(init_rate=0.99, length_variance="tight")
    result = pick_winner(profile, 50)
    assert result is not None
    signal, _ = result
    assert signal == "bot_or_automated_poster"


@pytest.mark.unit
def test_pick_winner_returns_none_when_no_match() -> None:
    # Mid-range values match neither recipe
    profile = _profile(init_rate=0.5, length_variance="varied")
    result = pick_winner(profile, 50)
    assert result is None


@pytest.mark.unit
def test_slots_present_true_when_all_present() -> None:
    profile = _profile(init_rate=0.02)
    assert slots_present(profile, ("interaction_summary.conversation_initiation_rate",)) is True


@pytest.mark.unit
def test_slots_present_false_when_missing() -> None:
    profile = _profile()
    assert slots_present(profile, ("interaction_summary.conversation_initiation_rate",)) is False


@pytest.mark.unit
def test_slots_present_false_when_value_is_none() -> None:
    profile = _profile()
    profile.interaction_summary["conversation_initiation_rate"] = {"value": None}
    assert slots_present(profile, ("interaction_summary.conversation_initiation_rate",)) is False


@pytest.mark.unit
def test_get_slot_value_returns_value() -> None:
    profile = _profile(init_rate=0.42)
    val = get_slot_value(profile, "interaction_summary.conversation_initiation_rate")
    assert val == pytest.approx(0.42)


@pytest.mark.unit
def test_get_slot_value_returns_none_for_missing() -> None:
    profile = _profile()
    assert get_slot_value(profile, "interaction_summary.conversation_initiation_rate") is None


@pytest.mark.unit
def test_get_slot_value_returns_none_for_missing_block() -> None:
    profile = _profile()
    assert get_slot_value(profile, "nonexistent_block.some_key") is None
