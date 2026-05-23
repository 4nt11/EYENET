"""Calibration assertions for the simhash linker comparators.

The Spanish slice is DISABLED in v0 (PLAN §M5, 2026-05-22) — these tests
guard that:

1. The committed baseline carries the disable sentinel.
2. The default ``LinkerThresholds`` config mirrors that disable.
3. AUC numbers haven't drifted from the recorded values (regression budget).

When BEHAVE-TEXT 0.0.2's minhash-with-shingles lands, the linker can be
re-enabled by re-running the grid; these tests will then assert real
thresholds instead of ``None``.

Run: ``pytest -m calibration tests/calibration/``
"""

from __future__ import annotations

import pytest

from eyenet.calibration.artifact import CalibrationArtifact, SimhashArtifactEntry
from eyenet.cli.config import LinkerThresholds


def _simhash(artifact: CalibrationArtifact, primitive: str, language: str) -> SimhashArtifactEntry:
    for s in artifact.simhash:
        if s.primitive == primitive and s.language == language:
            return s
    msg = f"simhash entry primitive={primitive!r} lang={language!r} missing"
    raise AssertionError(msg)


@pytest.mark.calibration
def test_baseline_function_word_es_is_disabled(
    baseline: CalibrationArtifact,
) -> None:
    s = _simhash(baseline, "function_word_distribution_top50", "es")
    assert s.enabled is False
    assert s.chosen_threshold is None


@pytest.mark.calibration
def test_baseline_char_ngram_es_is_disabled(
    baseline: CalibrationArtifact,
) -> None:
    s = _simhash(baseline, "character_ngram_simhash", "es")
    assert s.enabled is False
    assert s.chosen_threshold is None


@pytest.mark.calibration
def test_config_default_mirrors_baseline_for_function_word_es() -> None:
    """If the artifact says disabled, the production config must agree."""
    t = LinkerThresholds()
    assert t.for_comparator("function_word_simhash_hamming", "es") is None


@pytest.mark.calibration
def test_config_default_mirrors_baseline_for_char_ngram_es() -> None:
    t = LinkerThresholds()
    assert t.for_comparator("char_ngram_simhash_hamming", "es") is None


@pytest.mark.calibration
def test_function_word_auc_within_regression_budget(
    baseline: CalibrationArtifact,
) -> None:
    """5% AUC regression budget (PLAN §7.6).

    Baseline AUC was 0.5546 at calibration time. Allow 5% degradation
    before failing — anything worse is a primitive regression worth
    investigating, even on a disabled comparator (the grid math should
    stay stable).
    """
    s = _simhash(baseline, "function_word_distribution_top50", "es")
    # Sanity: AUC must at least be above 0.5 (worse-than-random would
    # indicate the within/cross sets got swapped or the primitive broke).
    assert s.auc > 0.50, f"AUC {s.auc} indicates broken signal"
    # Locked baseline: anything below 0.5546 * 0.95 = 0.527 means drift.
    assert s.auc >= 0.527


@pytest.mark.calibration
def test_char_ngram_auc_within_regression_budget(
    baseline: CalibrationArtifact,
) -> None:
    s = _simhash(baseline, "character_ngram_simhash", "es")
    assert s.auc > 0.50
    # Baseline 0.6776, 5% drop floor = 0.644.
    assert s.auc >= 0.644


@pytest.mark.calibration
def test_simhash_baseline_carries_actor_counts(
    baseline: CalibrationArtifact,
) -> None:
    """Documents the corpus the baseline was calibrated against."""
    assert baseline.actor_count_simhash_qualifying == 73
    assert baseline.min_messages == 50
