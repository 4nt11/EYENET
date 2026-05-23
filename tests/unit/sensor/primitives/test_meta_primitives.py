"""Unit tests for the eight meta.* primitives + the shared kernel.

Covers the BEHAVE-TEXT 0.1.2 corpus-level primitives wired in M5.5.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from behave_text.spec import PRIMITIVE_REGISTRY

from eyenet.sensor.primitives import (
    meta_active_days,
    meta_activity_density,
    meta_corpus_span_days,
    meta_fingerprint_confidence,
    meta_first_seen_ts,
    meta_last_seen_ts,
    meta_msg_per_day,
    meta_total_messages,
)
from eyenet.sensor.primitives._meta_kernel import (
    CONFIDENCE_HEURISTIC_TAG,
    CONFIDENCE_NUMERIC,
    compute_meta_stats,
)


def _corpus(timestamps: list[datetime]) -> list[tuple[datetime, UUID, str]]:
    return [(ts, uuid4(), f"ref:{i}") for i, ts in enumerate(timestamps)]


def _span(days: float, count: int, start: datetime | None = None) -> list[datetime]:
    """Evenly-spaced timestamps over `days` days, total `count` messages."""
    base = start or datetime(2026, 4, 1, tzinfo=UTC)
    if count == 1:
        return [base]
    step = timedelta(days=days / (count - 1))
    return [base + step * i for i in range(count)]


# ─── kernel ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_kernel_empty_corpus_returns_none() -> None:
    assert compute_meta_stats([]) is None


@pytest.mark.unit
def test_kernel_single_message_undefined_rates() -> None:
    stats = compute_meta_stats(_corpus(_span(0.0, 1)))
    assert stats is not None
    assert stats.total_messages == 1
    assert stats.corpus_span_days == 0.0
    assert stats.msg_per_day is None
    assert stats.active_days == 1
    assert stats.activity_density is None
    assert stats.first_seen_ts == stats.last_seen_ts
    assert stats.fingerprint_confidence == "low"


@pytest.mark.unit
def test_kernel_multi_day_actor_computes_rates() -> None:
    # 200 messages over 10 days, spread across ~10 calendar days
    stats = compute_meta_stats(_corpus(_span(10.0, 200)))
    assert stats is not None
    assert stats.total_messages == 200
    assert stats.corpus_span_days == pytest.approx(10.0, abs=1e-6)
    assert stats.msg_per_day == pytest.approx(20.0, abs=1e-6)
    assert stats.active_days <= 11  # at most ceil(10)+1 calendar buckets
    assert stats.active_days >= 10
    assert stats.activity_density is not None
    assert 0.0 < stats.activity_density <= 1.0
    assert stats.fingerprint_confidence == "high"  # 200 msgs ≥ 100, 10+ days ≥ 7


@pytest.mark.unit
def test_kernel_confidence_classification() -> None:
    # Low: 5 msgs over 1 day
    low_stats = compute_meta_stats(_corpus(_span(1.0, 5)))
    assert low_stats is not None
    assert low_stats.fingerprint_confidence == "low"

    # Medium: 50 msgs over 3 days (≥30 msgs, ≥2 active days, <100)
    med_stats = compute_meta_stats(_corpus(_span(3.0, 50)))
    assert med_stats is not None
    assert med_stats.fingerprint_confidence == "medium"

    # High: 150 msgs over 14 days
    high_stats = compute_meta_stats(_corpus(_span(14.0, 150)))
    assert high_stats is not None
    assert high_stats.fingerprint_confidence == "high"


@pytest.mark.unit
def test_kernel_rejects_naive_datetime() -> None:
    naive_ts = datetime(2026, 4, 1)  # noqa: DTZ001 — intentional naive datetime for test
    corpus: list[tuple[datetime, UUID, str]] = [(naive_ts, uuid4(), "ref:0")]
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_meta_stats(corpus)


# ─── numeric primitives (5) ───────────────────────────────────────────────


@pytest.mark.unit
def test_total_messages_emits_count_as_float() -> None:
    obs = meta_total_messages.compute(corpus=_corpus(_span(5.0, 42)), bodies={})
    assert obs is not None
    assert obs.primitive == "meta.total_messages"
    assert obs.value == 42.0
    PRIMITIVE_REGISTRY[obs.primitive].validate_value(obs.value)


@pytest.mark.unit
def test_corpus_span_days_emits_float() -> None:
    obs = meta_corpus_span_days.compute(corpus=_corpus(_span(7.5, 40)), bodies={})
    assert obs is not None
    assert obs.primitive == "meta.corpus_span_days"
    assert isinstance(obs.value, float)
    assert obs.value == pytest.approx(7.5, abs=1e-6)
    PRIMITIVE_REGISTRY[obs.primitive].validate_value(obs.value)


@pytest.mark.unit
def test_msg_per_day_emits_rate() -> None:
    obs = meta_msg_per_day.compute(corpus=_corpus(_span(10.0, 200)), bodies={})
    assert obs is not None
    assert obs.primitive == "meta.msg_per_day"
    assert obs.value == pytest.approx(20.0, abs=1e-6)
    PRIMITIVE_REGISTRY[obs.primitive].validate_value(obs.value)


@pytest.mark.unit
def test_msg_per_day_suppressed_for_single_day_actor() -> None:
    # 5 messages all at the same instant -> span=0 -> rate undefined
    same_ts = datetime(2026, 4, 1, tzinfo=UTC)
    corpus = _corpus([same_ts] * 5)
    assert meta_msg_per_day.compute(corpus=corpus, bodies={}) is None


@pytest.mark.unit
def test_active_days_emits_count() -> None:
    obs = meta_active_days.compute(corpus=_corpus(_span(10.0, 200)), bodies={})
    assert obs is not None
    assert obs.primitive == "meta.active_days"
    assert isinstance(obs.value, float)
    assert obs.value >= 10.0
    PRIMITIVE_REGISTRY[obs.primitive].validate_value(obs.value)


@pytest.mark.unit
def test_activity_density_in_unit_interval() -> None:
    obs = meta_activity_density.compute(corpus=_corpus(_span(10.0, 200)), bodies={})
    assert obs is not None
    assert obs.primitive == "meta.activity_density"
    assert 0.0 < obs.value <= 1.0
    PRIMITIVE_REGISTRY[obs.primitive].validate_value(obs.value)


@pytest.mark.unit
def test_activity_density_suppressed_for_single_day_actor() -> None:
    same_ts = datetime(2026, 4, 1, tzinfo=UTC)
    corpus = _corpus([same_ts] * 5)
    assert meta_activity_density.compute(corpus=corpus, bodies={}) is None


# ─── metadata primitives (3) ──────────────────────────────────────────────


@pytest.mark.unit
def test_first_seen_ts_emits_iso_string() -> None:
    obs = meta_first_seen_ts.compute(corpus=_corpus(_span(10.0, 200)), bodies={})
    assert obs is not None
    assert obs.primitive == "meta.first_seen_ts"
    assert isinstance(obs.value, str)
    assert obs.value.startswith("2026-04-01T00:00:00")
    PRIMITIVE_REGISTRY[obs.primitive].validate_value(obs.value)


@pytest.mark.unit
def test_last_seen_ts_emits_iso_string() -> None:
    obs = meta_last_seen_ts.compute(corpus=_corpus(_span(10.0, 200)), bodies={})
    assert obs is not None
    assert obs.primitive == "meta.last_seen_ts"
    assert isinstance(obs.value, str)
    assert obs.value.startswith("2026-04-11")
    PRIMITIVE_REGISTRY[obs.primitive].validate_value(obs.value)


@pytest.mark.unit
def test_fingerprint_confidence_emits_categorical() -> None:
    obs = meta_fingerprint_confidence.compute(corpus=_corpus(_span(10.0, 200)), bodies={})
    assert obs is not None
    assert obs.primitive == "meta.fingerprint_confidence"
    assert obs.value in {"low", "medium", "high"}
    PRIMITIVE_REGISTRY[obs.primitive].validate_value(obs.value)
    # Source label must declare the heuristic version per the spec contract
    assert CONFIDENCE_HEURISTIC_TAG in obs.source


# ─── all-eight cross-cutting ──────────────────────────────────────────────


@pytest.mark.unit
def test_all_eight_emit_on_normal_corpus() -> None:
    corpus = _corpus(_span(10.0, 200))
    bodies: dict[str, str] = {}

    obs_set = [
        meta_total_messages.compute(corpus=corpus, bodies=bodies),
        meta_corpus_span_days.compute(corpus=corpus, bodies=bodies),
        meta_msg_per_day.compute(corpus=corpus, bodies=bodies),
        meta_active_days.compute(corpus=corpus, bodies=bodies),
        meta_activity_density.compute(corpus=corpus, bodies=bodies),
        meta_first_seen_ts.compute(corpus=corpus, bodies=bodies),
        meta_last_seen_ts.compute(corpus=corpus, bodies=bodies),
        meta_fingerprint_confidence.compute(corpus=corpus, bodies=bodies),
    ]
    assert all(obs is not None for obs in obs_set)
    # All eight share the same window
    windows = {(obs.window.start_ts, obs.window.end_ts) for obs in obs_set if obs is not None}
    assert len(windows) == 1
    # All eight carry the v1 heuristic tag in their source label
    for obs in obs_set:
        assert obs is not None
        assert CONFIDENCE_HEURISTIC_TAG in obs.source


@pytest.mark.unit
def test_confidence_numeric_mapping_spans_unit_interval() -> None:
    assert CONFIDENCE_NUMERIC == {"low": 0.3, "medium": 0.6, "high": 0.9}


@pytest.mark.unit
def test_empty_corpus_emits_none_for_all_eight() -> None:
    bodies: dict[str, str] = {}
    empty: list[tuple[datetime, UUID, str]] = []
    for compute_fn in (
        meta_total_messages.compute,
        meta_corpus_span_days.compute,
        meta_msg_per_day.compute,
        meta_active_days.compute,
        meta_activity_density.compute,
        meta_first_seen_ts.compute,
        meta_last_seen_ts.compute,
        meta_fingerprint_confidence.compute,
    ):
        assert compute_fn(corpus=empty, bodies=bodies) is None
