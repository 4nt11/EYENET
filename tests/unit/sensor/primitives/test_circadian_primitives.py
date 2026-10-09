"""Unit tests for the four circadian.* primitives + the shared kernel additions.

BEHAVE-TEXT 0.1.4 hour/day activity-rhythm primitives, computed in the same
compute_meta_stats pass as the meta.* set.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from behave_text.spec import PRIMITIVE_REGISTRY

from eyenet.sensor.primitives import (
    circadian_dow_histogram,
    circadian_hour_dow_histogram,
    circadian_hour_histogram,
    circadian_quiet_span,
)
from eyenet.sensor.primitives._meta_kernel import _longest_quiet_span, compute_meta_stats


def _corpus(timestamps: list[datetime]) -> list[tuple[datetime, UUID, str]]:
    actor = uuid4()
    return [(ts, actor, f"ref:{i}") for i, ts in enumerate(timestamps)]


def _active_hours(hours: list[int], days: int = 20) -> list[datetime]:
    """A message at each given UTC hour, every day for `days` days (Mondays start)."""
    base = datetime(2026, 9, 7, tzinfo=UTC)  # a Monday
    return [base + timedelta(days=d, hours=h) for d in range(days) for h in hours]


# ─── histograms ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_histograms_normalized_and_sized() -> None:
    stats = compute_meta_stats(_corpus(_active_hours([14, 16, 20])))
    assert stats is not None
    assert len(stats.hour_histogram) == 24
    assert len(stats.dow_histogram) == 7
    assert len(stats.hour_dow_histogram) == 168
    assert sum(stats.hour_histogram) == pytest.approx(1.0)
    assert sum(stats.dow_histogram) == pytest.approx(1.0)
    assert sum(stats.hour_dow_histogram) == pytest.approx(1.0)


@pytest.mark.unit
def test_marginals_are_joint_axis_sums() -> None:
    stats = compute_meta_stats(_corpus(_active_hours([3, 9, 15, 21])))
    assert stats is not None
    # hour marginal = sum over the 7 dow rows at each hour
    for h in range(24):
        col = sum(stats.hour_dow_histogram[d * 24 + h] for d in range(7))
        assert col == pytest.approx(stats.hour_histogram[h])
    # dow marginal = sum over the 24 hours in each row
    for d in range(7):
        row = sum(stats.hour_dow_histogram[d * 24 + h] for h in range(24))
        assert row == pytest.approx(stats.dow_histogram[d])


@pytest.mark.unit
def test_hour_bins_land_in_utc_hour() -> None:
    stats = compute_meta_stats(_corpus(_active_hours([14, 16, 20])))
    assert stats is not None
    nonzero = [h for h, v in enumerate(stats.hour_histogram) if v > 0]
    assert nonzero == [14, 16, 20]


@pytest.mark.unit
def test_dow_monday_is_zero() -> None:
    # Only Mondays (base is a Monday, step 7 days).
    base = datetime(2026, 9, 7, tzinfo=UTC)  # Monday
    stats = compute_meta_stats(_corpus([base + timedelta(days=7 * i, hours=12) for i in range(5)]))
    assert stats is not None
    assert stats.dow_histogram[0] == pytest.approx(1.0)
    assert sum(stats.dow_histogram[1:]) == pytest.approx(0.0)


# ─── quiet span ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_quiet_span_wraps_midnight() -> None:
    # Active 14..22 UTC -> the long quiet run is 23 -> 14 (crosses midnight).
    stats = compute_meta_stats(_corpus(_active_hours([14, 15, 16, 18, 20, 22])))
    assert stats is not None
    assert stats.quiet_span_utc is not None
    start, end = stats.quiet_span_utc
    assert start > end  # wrap
    assert (start, end) == (23, 14)


@pytest.mark.unit
def test_quiet_span_gated_below_threshold() -> None:
    # 10 messages over 1 day: below the >=30 msgs / >=2 active-days gate -> None.
    base = datetime(2026, 9, 7, tzinfo=UTC)
    stats = compute_meta_stats(_corpus([base + timedelta(hours=h) for h in range(10)]))
    assert stats is not None
    assert stats.quiet_span_utc is None


@pytest.mark.unit
def test_quiet_span_low_not_zero() -> None:
    # A bin with a trickle (< 10% of peak) still counts as quiet.
    peak = [100 if h in (14, 15, 16) else 0 for h in range(24)]
    peak[3] = 2  # 2 < 10% of 100 -> still quiet, must not break the run
    span = _longest_quiet_span(peak)
    assert span is not None
    start, end = span
    # quiet run covers hour 3 despite the trickle
    run = [(start + k) % 24 for k in range((end - start) % 24)]
    assert 3 in run


# ─── primitive observations validate against the registry ───────────────────


@pytest.mark.unit
def test_primitives_emit_registry_valid_observations() -> None:
    corpus = _corpus(_active_hours([14, 16, 20]))
    for mod, length in (
        (circadian_hour_histogram, 24),
        (circadian_dow_histogram, 7),
        (circadian_hour_dow_histogram, 168),
    ):
        obs = mod.compute(corpus=corpus, bodies={})
        assert obs is not None
        assert len(obs.value) == length
        PRIMITIVE_REGISTRY[mod.PRIMITIVE_NAME].validate_value(obs.value)


@pytest.mark.unit
def test_quiet_span_primitive_omits_when_gated() -> None:
    base = datetime(2026, 9, 7, tzinfo=UTC)
    thin = _corpus([base + timedelta(hours=h) for h in range(5)])
    assert circadian_quiet_span.compute(corpus=thin, bodies={}) is None

    rich = _corpus(_active_hours([14, 16, 20]))
    obs = circadian_quiet_span.compute(corpus=rich, bodies={})
    assert obs is not None
    assert len(obs.value) == 2
    PRIMITIVE_REGISTRY[circadian_quiet_span.PRIMITIVE_NAME].validate_value(obs.value)


@pytest.mark.unit
def test_empty_corpus_emits_nothing() -> None:
    for mod in (
        circadian_hour_histogram,
        circadian_dow_histogram,
        circadian_hour_dow_histogram,
        circadian_quiet_span,
    ):
        assert mod.compute(corpus=[], bodies={}) is None
