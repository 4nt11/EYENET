"""Calibration test stubs for recipe threshold validation.

These tests are EXCLUDED from the default run (`-m "not calibration"`).
They will be fleshed out in M5 when the Rutify corpus grid lands.

Run explicitly with: pytest -m calibration tests/calibration/
"""

from __future__ import annotations

import pytest


@pytest.mark.calibration
def test_lurker_or_observer_thresholds_calibrated() -> None:
    pytest.skip(
        "UNCALIBRATED: lurker_or_observer threshold requires Rutify corpus AUC grid (M5). "
        "Target: AUC > 0.85 on held-out labeled set."
    )


@pytest.mark.calibration
def test_bot_or_automated_poster_thresholds_calibrated() -> None:
    pytest.skip(
        "UNCALIBRATED: bot_or_automated_poster thresholds require Rutify corpus grid (M5). "
        "Target: precision > 0.90, recall > 0.80 on labeled set. "
        "Also: add punctuation_style + typo_signature to recipe once calibrated."
    )


@pytest.mark.calibration
def test_mattr_discrimination_auc() -> None:
    pytest.skip(
        "BEHAVE-TEXT regression budget: MATTR discrimination AUC must not drop"
        " > 5% across release. Needs labeled corpus (M5). Ref: PLAN §7.6."
    )
