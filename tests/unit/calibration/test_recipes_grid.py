"""Unit tests for :mod:`eyenet.calibration.recipes_grid`."""

from __future__ import annotations

import pytest

from eyenet.calibration.interaction import ActorStats
from eyenet.calibration.labels import ActorLabel
from eyenet.calibration.recipes_grid import (
    AxisGroup,
    AxisThreshold,
    search_bot_or_automated_poster,
    search_chatty_member,
    search_lurker_or_observer,
)


def _stats(
    sender_id: int,
    *,
    msg_count: int = 100,
    init_rate: float = 0.5,
    msg_per_day: float = 50.0,
    corpus_span_days: float = 1.0,
    length_cv: float = 1.0,
    inter_msg_cv: float = 5.0,
    mattr: float = 0.85,
) -> ActorStats:
    return ActorStats(
        sender_id=sender_id,
        msg_count=msg_count,
        corpus_span_days=corpus_span_days,
        msg_per_day=msg_per_day,
        init_rate=init_rate,
        reply_rate=1.0 - init_rate,
        mention_rate=0.05,
        mean_msg_chars=20.0,
        median_msg_chars=18.0,
        length_cv=length_cv,
        inter_msg_p50=30.0,
        inter_msg_cv=inter_msg_cv,
        mattr=mattr,
    )


def _label(sender_id: int, label: str) -> ActorLabel:
    return ActorLabel(
        sender_id=sender_id,
        label=label,
        confidence="high",
        notes="",
    )


@pytest.mark.unit
def test_axis_threshold_evaluates_op_lte() -> None:
    s = _stats(1, init_rate=0.15)
    assert AxisThreshold("init_rate", "<=", 0.20).evaluate(s) is True
    assert AxisThreshold("init_rate", "<=", 0.10).evaluate(s) is False


@pytest.mark.unit
def test_axis_threshold_evaluates_op_gte() -> None:
    s = _stats(1, init_rate=0.99)
    assert AxisThreshold("init_rate", ">=", 0.95).evaluate(s) is True


@pytest.mark.unit
def test_axis_threshold_unknown_op_raises() -> None:
    s = _stats(1)
    with pytest.raises(ValueError, match="unknown op"):
        AxisThreshold("init_rate", "!=", 0.5).evaluate(s)  # type: ignore[arg-type]


@pytest.mark.unit
def test_axis_group_combines_with_and() -> None:
    s = _stats(1, init_rate=0.99, length_cv=0.1)
    g = AxisGroup(
        axes=(
            AxisThreshold("init_rate", ">=", 0.95),
            AxisThreshold("length_cv", "<=", 0.30),
        )
    )
    assert g.evaluate(s) is True
    # One axis fails → AND fails
    s2 = _stats(1, init_rate=0.99, length_cv=0.5)
    assert g.evaluate(s2) is False


@pytest.mark.unit
def test_bot_recipe_locked_axes_catch_synthetic_bot() -> None:
    bot = _stats(1, init_rate=1.0, length_cv=0.1)
    human = _stats(2, init_rate=0.6, length_cv=1.0)
    labels = {1: _label(1, "bot"), 2: _label(2, "normal")}
    rc = search_bot_or_automated_poster([bot, human], labels)
    assert rc.tp == 1
    assert rc.fp == 0
    assert rc.fn == 0
    assert rc.precision == pytest.approx(1.0)
    assert rc.recall == pytest.approx(1.0)


@pytest.mark.unit
def test_bot_recipe_axes_are_fixed_not_swept() -> None:
    # Even with adversarial labels, the bot recipe MUST keep operator-locked axes.
    labels = {1: _label(1, "bot")}
    stats = [_stats(1, init_rate=0.5, length_cv=0.5)]  # doesn't meet locked thresholds
    rc = search_bot_or_automated_poster(stats, labels)
    # Recipe still has its locked group; bot just isn't matched.
    assert len(rc.groups) == 1
    assert rc.tp == 0
    assert rc.fn == 1


@pytest.mark.unit
def test_lurker_recipe_catches_passive_responder() -> None:
    # Pattern A: low init_rate
    lurker = _stats(1, init_rate=0.10, msg_per_day=50.0, corpus_span_days=0.5)
    normal = _stats(2, init_rate=0.60, msg_per_day=50.0, corpus_span_days=0.5)
    labels = {1: _label(1, "lurker"), 2: _label(2, "normal")}
    rc = search_lurker_or_observer([lurker, normal], labels)
    assert rc.tp >= 1
    assert rc.fp == 0


@pytest.mark.unit
def test_lurker_recipe_catches_long_tail_visitor() -> None:
    # Pattern B: low msg_per_day with long span
    visitor = _stats(1, init_rate=0.50, msg_per_day=1.2, corpus_span_days=45.0)
    bursty_normal = _stats(2, init_rate=0.50, msg_per_day=100.0, corpus_span_days=0.5)
    labels = {1: _label(1, "lurker"), 2: _label(2, "normal")}
    rc = search_lurker_or_observer([visitor, bursty_normal], labels)
    assert rc.tp >= 1
    assert rc.fp == 0


@pytest.mark.unit
def test_chatty_member_msg_count_threshold() -> None:
    # 3 chatty (high msg_count), 3 normal (low msg_count)
    stats = [
        _stats(1, msg_count=500),
        _stats(2, msg_count=400),
        _stats(3, msg_count=300),
        _stats(4, msg_count=50),
        _stats(5, msg_count=60),
        _stats(6, msg_count=80),
    ]
    labels = {
        1: _label(1, "chatty_member"),
        2: _label(2, "chatty_member"),
        3: _label(3, "chatty_member"),
        4: _label(4, "normal"),
        5: _label(5, "normal"),
        6: _label(6, "normal"),
    }
    rc = search_chatty_member(stats, labels, min_precision=0.70)
    assert rc.tp == 3
    assert rc.fp == 0
    assert rc.precision == pytest.approx(1.0)
    assert rc.recall == pytest.approx(1.0)


@pytest.mark.unit
def test_recipe_calibration_matches_consistent_with_metrics() -> None:
    """The .matches() predicate must agree with the stored confusion matrix."""
    stats = [
        _stats(1, msg_count=500),
        _stats(2, msg_count=50),
    ]
    labels = {1: _label(1, "chatty_member"), 2: _label(2, "normal")}
    rc = search_chatty_member(stats, labels)
    predicted_positive = sum(1 for s in stats if rc.matches(s))
    assert predicted_positive == rc.tp + rc.fp
