"""Unit tests for circadian -> timezone inference (the smart-consumer side)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.engine.timezone_inference import infer_timezone

pytestmark = pytest.mark.unit

# Southern-hemisphere summer: Chile/Argentina/Brazil sit at UTC-3 on this date.
_SUMMER = datetime(2026, 1, 15, tzinfo=UTC)


def _hist(active_hours: range | list[int]) -> list[float]:
    h = [0.0] * 24
    for hour in active_hours:
        h[hour % 24] = 1.0
    total = sum(h)
    return [x / total for x in h]


@pytest.mark.unit
def test_santiago_from_circadian_plus_dialect() -> None:
    # Quiet 03:00-10:00 UTC -> midpoint 06:30 -> sleep-center 03:30 local -> UTC-3.
    hist = _hist(list(range(10, 24)) + list(range(0, 3)))  # active 10->02 UTC
    tz = infer_timezone(
        hour_histogram=hist,
        quiet_span_utc=(3, 10),
        total_messages=500,
        dialect_region="es-CL",
        at=_SUMMER,
    )
    assert tz.offset_hours == -3
    assert tz.zone_best == "America/Santiago"
    assert tz.confidence == "high"
    assert "lexical.dialect_region=es-CL" in tz.supporting_signals


@pytest.mark.unit
def test_offset_only_gives_candidate_list_not_single_zone() -> None:
    hist = _hist(list(range(10, 24)) + list(range(0, 3)))
    tz = infer_timezone(
        hour_histogram=hist, quiet_span_utc=(3, 10), total_messages=500, at=_SUMMER
    )
    assert tz.offset_hours == -3
    assert tz.zone_best is None  # no second signal -> never assert one zone
    assert "America/Sao_Paulo" in tz.zone_candidates
    assert tz.confidence == "medium"


@pytest.mark.unit
def test_dialect_offset_mismatch_is_flagged() -> None:
    # Dialect says Chile (-3/-4) but the clock says UTC+2 -> keep dialect zone, flag drift.
    hist = _hist(range(6, 20))
    tz = infer_timezone(
        hour_histogram=hist,
        quiet_span_utc=(22, 5),  # midpoint ~01:30 -> offset +2
        total_messages=500,
        dialect_region="es-CL",
        at=_SUMMER,
    )
    assert tz.offset_hours == 2
    assert tz.zone_best == "America/Santiago"  # dialect prior kept
    assert "offset_dialect_mismatch" in tz.supporting_signals
    assert tz.confidence == "medium"  # not high: offset disagrees


@pytest.mark.unit
def test_thin_actor_without_quiet_span_is_low_confidence() -> None:
    hist = _hist(range(12, 18))
    tz = infer_timezone(
        hour_histogram=hist, quiet_span_utc=None, total_messages=12, at=_SUMMER
    )
    assert tz.confidence == "low"
    assert tz.offset_hours is not None  # still a rough guess from the histogram
    assert "circadian.hour_histogram" in tz.supporting_signals


@pytest.mark.unit
def test_empty_histogram_infers_nothing() -> None:
    tz = infer_timezone(
        hour_histogram=[0.0] * 24, quiet_span_utc=None, total_messages=0, at=_SUMMER
    )
    assert tz.confidence == "none"
    assert tz.offset_hours is None
    assert tz.zone_best is None

    tz2 = infer_timezone(
        hour_histogram=None, quiet_span_utc=None, total_messages=0, at=_SUMMER
    )
    assert tz2.confidence == "none"


@pytest.mark.unit
def test_local_active_window_is_utc_shifted() -> None:
    hist = _hist(list(range(10, 24)) + list(range(0, 3)))
    tz = infer_timezone(
        hour_histogram=hist, quiet_span_utc=(3, 10), total_messages=500, at=_SUMMER
    )
    # active UTC = complement of quiet (10 -> 03); shifted by -3 -> (07 -> 00).
    assert tz.local_active_window == (7, 0)
    assert tz.quiet_window_utc == (3, 10)
