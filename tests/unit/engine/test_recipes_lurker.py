"""Unit tests for the lurker_or_observer recipe."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.attribution import ProfileRow
from eyenet.engine.recipes.lurker_or_observer import (
    MAX_INITIATION_RATE,
    MAX_MSG_PER_DAY,
    MIN_CORPUS_SPAN_DAYS,
    MIN_OBSERVATION_COUNT,
    LurkerOrObserverRecipe,
)

_UUID = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 1, tzinfo=UTC)


def _slot(value: object) -> dict[str, object]:
    return {
        "value": value,
        "last_observation_id": str(_UUID),
        "derived_from_observation_count": 50,
    }


def _profile(
    init_rate: float | None = None,
    msg_per_day: float | None = None,
    corpus_span_days: float | None = None,
) -> ProfileRow:
    interaction: dict[str, object] = {}
    if init_rate is not None:
        interaction["conversation_initiation_rate"] = _slot(init_rate)
    temporal: dict[str, object] = {}
    if msg_per_day is not None:
        temporal["msg_per_day"] = _slot(msg_per_day)
    if corpus_span_days is not None:
        temporal["corpus_span_days"] = _slot(corpus_span_days)
    return ProfileRow(
        id=_UUID,
        actor_id=_UUID,
        version=1,
        is_current=True,
        role_signal=None,
        role_confidence=0.0,
        interaction_summary=interaction,
        temporal_summary=temporal,
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
    # 0.50 is above the calibrated 0.20 threshold.
    result = _recipe.evaluate(_profile(init_rate=0.50), 50)
    assert result.matches is False
    assert result.confidence == 0.0


@pytest.mark.unit
def test_at_threshold_boundary_does_match() -> None:
    # Exactly at threshold → still "≤", so matches
    result = _recipe.evaluate(_profile(init_rate=MAX_INITIATION_RATE), 50)
    assert result.matches is True


@pytest.mark.unit
def test_missing_slot_returns_no_match() -> None:
    result = _recipe.evaluate(_profile(init_rate=None), 50)
    assert result.matches is False


@pytest.mark.unit
def test_reasoning_carries_calibrated_true() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.01), 50)
    assert result.reasoning.get("calibrated") is True


@pytest.mark.unit
def test_reasoning_contains_threshold() -> None:
    result = _recipe.evaluate(_profile(init_rate=0.01), 50)
    assert "threshold_max_initiation_rate" in result.reasoning


@pytest.mark.unit
def test_low_observation_count_reduces_confidence() -> None:
    high_count = _recipe.evaluate(_profile(init_rate=0.01), MIN_OBSERVATION_COUNT)
    low_count = _recipe.evaluate(_profile(init_rate=0.01), 1)
    assert low_count.confidence < high_count.confidence


# ─── Pattern B — long-tail occasional presence (M5.5) ────────────────────


@pytest.mark.unit
def test_pattern_b_fires_on_low_rate_long_span() -> None:
    # No init_rate; only temporal slots populated. Should still fire via B.
    result = _recipe.evaluate(
        _profile(msg_per_day=1.0, corpus_span_days=14.0),
        50,
    )
    assert result.matches is True
    assert result.reasoning["matched_patterns"] == ["B"]


@pytest.mark.unit
def test_pattern_b_no_match_when_rate_too_high() -> None:
    result = _recipe.evaluate(
        _profile(msg_per_day=MAX_MSG_PER_DAY + 0.1, corpus_span_days=30.0),
        50,
    )
    assert result.matches is False


@pytest.mark.unit
def test_pattern_b_no_match_when_span_too_short() -> None:
    # Rate is fine but span is below the floor.
    result = _recipe.evaluate(
        _profile(msg_per_day=0.5, corpus_span_days=MIN_CORPUS_SPAN_DAYS - 0.1),
        50,
    )
    assert result.matches is False


@pytest.mark.unit
def test_pattern_b_boundary_match() -> None:
    # Exactly at both thresholds.
    result = _recipe.evaluate(
        _profile(msg_per_day=MAX_MSG_PER_DAY, corpus_span_days=MIN_CORPUS_SPAN_DAYS),
        50,
    )
    assert result.matches is True


@pytest.mark.unit
def test_both_patterns_match_fires_once_with_both_listed() -> None:
    # Active responder with low msg_per_day over a long span — matches A and B.
    result = _recipe.evaluate(
        _profile(init_rate=0.05, msg_per_day=0.5, corpus_span_days=21.0),
        50,
    )
    assert result.matches is True
    assert result.reasoning["matched_patterns"] == ["A", "B"]


@pytest.mark.unit
def test_pattern_a_alone_lists_only_a() -> None:
    result = _recipe.evaluate(
        _profile(init_rate=0.05, msg_per_day=10.0, corpus_span_days=1.0),
        50,
    )
    assert result.matches is True
    assert result.reasoning["matched_patterns"] == ["A"]


@pytest.mark.unit
def test_no_slots_at_all_skips_recipe() -> None:
    result = _recipe.evaluate(_profile(), 50)
    assert result.matches is False
    assert result.reasoning.get("skip_reason") == "required_slots_absent"


@pytest.mark.unit
def test_reasoning_carries_both_thresholds() -> None:
    result = _recipe.evaluate(
        _profile(init_rate=0.05, msg_per_day=0.5, corpus_span_days=14.0),
        50,
    )
    assert "threshold_max_msg_per_day" in result.reasoning
    assert "threshold_min_corpus_span_days" in result.reasoning
