"""Unit tests for :mod:`eyenet.calibration.simhash_grid`.

These exercise the analytic layer (AUC, threshold sweep, precision-floor
picker) without invoking the primitives — the real-corpus run lives in the
calibration suite proper.
"""

from __future__ import annotations

import pytest

from eyenet.calibration.simhash_grid import (
    _pick_f1_max,
    _pick_precision_floor,
    _threshold_sweep,
    mann_whitney_auc,
)


@pytest.mark.unit
def test_mann_whitney_auc_perfect_separation() -> None:
    # Every within-author distance is strictly smaller than every cross.
    within = [1, 2, 3]
    cross = [10, 11, 12]
    assert mann_whitney_auc(within, cross) == 1.0


@pytest.mark.unit
def test_mann_whitney_auc_identical_distributions() -> None:
    # Identical distributions → 0.5 (ties resolved by mid-rank).
    within = [5, 5, 5]
    cross = [5, 5, 5]
    assert mann_whitney_auc(within, cross) == 0.5


@pytest.mark.unit
def test_mann_whitney_auc_empty_inputs_return_half() -> None:
    assert mann_whitney_auc([], [1, 2]) == 0.5
    assert mann_whitney_auc([1, 2], []) == 0.5


@pytest.mark.unit
def test_mann_whitney_auc_inverted_returns_low() -> None:
    # Within > cross → AUC well below 0.5
    within = [10, 11, 12]
    cross = [1, 2, 3]
    assert mann_whitney_auc(within, cross) == 0.0


@pytest.mark.unit
def test_threshold_sweep_covers_all_integers() -> None:
    rows = _threshold_sweep([2, 4], [6, 8])
    assert [r.threshold for r in rows] == list(range(0, 65))


@pytest.mark.unit
def test_threshold_sweep_perfect_separation_has_perfect_f1() -> None:
    rows = _threshold_sweep([1, 2], [10, 11])
    # At threshold=2: both within in, both cross out → P=1.0 R=1.0 F1=1.0
    row = rows[2]
    assert row.precision == pytest.approx(1.0)
    assert row.recall == pytest.approx(1.0)
    assert row.f1 == pytest.approx(1.0)


@pytest.mark.unit
def test_pick_f1_max_prefers_tighter_threshold_on_tie() -> None:
    rows = _threshold_sweep([0, 0], [5, 5])
    best = _pick_f1_max(rows)
    # F1=1.0 from t=0 onward; tighter wins.
    assert best.threshold == 0


@pytest.mark.unit
def test_pick_precision_floor_prefers_higher_recall() -> None:
    # Construct sweep with monotone recall growth at constant high precision.
    # Within at 1, 5, 9; cross at 50. Recall climbs across t=1..9 with P=1.0.
    rows = _threshold_sweep([1, 5, 9], [50])
    chosen = _pick_precision_floor(rows, min_precision=0.99)
    # Best operating point: t=9 captures all 3 within with no false positives.
    # Recall=1.0, P=1.0. Below t=9, recall is lower.
    assert chosen.threshold == 9
    assert chosen.precision == pytest.approx(1.0)
    assert chosen.recall == pytest.approx(1.0)


@pytest.mark.unit
def test_pick_precision_floor_ties_broken_by_tighter_threshold() -> None:
    # Plateau case: recall hits 1.0 at t=1 and stays there until t=9.
    # Picker prefers tighter threshold on recall-tie (precision-first).
    rows = _threshold_sweep([1, 1, 1], [10, 10, 10])
    chosen = _pick_precision_floor(rows, min_precision=0.99)
    assert chosen.threshold == 1
    assert chosen.recall == pytest.approx(1.0)


@pytest.mark.unit
def test_pick_precision_floor_falls_back_to_max_precision_when_unreachable() -> None:
    # Within and cross fully overlap → no threshold reaches P=0.70.
    rows = _threshold_sweep([1, 5, 9], [1, 5, 9])
    chosen = _pick_precision_floor(rows, min_precision=0.70)
    # Fallback: the row with the highest precision in the sweep. With this
    # overlap the picker still chooses the tightest such row.
    assert chosen.precision < 0.70  # the bar IS unreachable
    # And the row chosen IS in the sweep range.
    assert 0 <= chosen.threshold <= 64
