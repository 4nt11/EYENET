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


# ─── M6.5 spaCy trio (calibrated against Rutify 2026-05-23) ──────────────────
# Both new simhashes failed to clear the precision_floor:0.70 strategy at
# any threshold, mirroring the M5 outcome on the two earlier simhashes.
# Operator decision (2026-05-23): disable both for Spanish in the default
# LinkerThresholds, recorded as ``enabled=False`` in the committed
# baseline. Re-enable when BEHAVE-TEXT minhash-with-shingles lands or
# when a non-Spanish corpus is calibrated.


@pytest.mark.calibration
def test_baseline_pos_ngram_es_is_disabled(baseline: CalibrationArtifact) -> None:
    s = _simhash(baseline, "pos_ngram_signature", "es")
    assert s.enabled is False
    assert s.chosen_threshold is None


@pytest.mark.calibration
def test_baseline_optional_grammar_es_is_disabled(baseline: CalibrationArtifact) -> None:
    s = _simhash(baseline, "optional_grammar_signature", "es")
    assert s.enabled is False
    assert s.chosen_threshold is None


@pytest.mark.calibration
def test_config_default_pos_ngram_es_is_disabled() -> None:
    """Production config mirrors the baseline disable for Spanish."""
    t = LinkerThresholds()
    assert t.for_comparator("pos_ngram_simhash_hamming", "es") is None


@pytest.mark.calibration
def test_config_default_optional_grammar_es_is_disabled() -> None:
    t = LinkerThresholds()
    assert t.for_comparator("optional_grammar_simhash_hamming", "es") is None


@pytest.mark.calibration
def test_pos_ngram_auc_within_regression_budget(baseline: CalibrationArtifact) -> None:
    """5% AUC regression budget (PLAN §7.6).

    Baseline AUC was 0.6108 at calibration time (2026-05-23). Floor at
    0.6108 * 0.95 = 0.580. Anything worse indicates a primitive regression
    even though the comparator is disabled at the config layer — the grid
    math must stay stable.
    """
    s = _simhash(baseline, "pos_ngram_signature", "es")
    assert s.auc > 0.50, f"AUC {s.auc} indicates broken signal"
    assert s.auc >= 0.580


@pytest.mark.calibration
def test_optional_grammar_auc_within_regression_budget(baseline: CalibrationArtifact) -> None:
    """5% AUC regression budget — baseline 0.6319, floor 0.600."""
    s = _simhash(baseline, "optional_grammar_signature", "es")
    assert s.auc > 0.50
    assert s.auc >= 0.600


@pytest.mark.calibration
def test_simhash_grid_default_includes_m6_5_trio() -> None:
    """The default grid run iterates the two new simhash primitives."""
    import inspect

    from eyenet.calibration.simhash_grid import run as grid_run

    sig = inspect.signature(grid_run)
    default_primitives: tuple[str, ...] = sig.parameters["primitives"].default
    assert "pos_ngram_signature" in default_primitives
    assert "optional_grammar_signature" in default_primitives


@pytest.mark.calibration
def test_all_four_es_simhashes_in_disabled_policy_set() -> None:
    """``_ES_DISABLED_PRIMITIVES`` lists every simhash disabled for Spanish.

    Adding a new ES-failing simhash requires adding it here; this test
    is the gate that catches future additions where someone bumps the
    primitive but forgets the policy entry.
    """
    from eyenet.calibration.artifact import _ES_DISABLED_PRIMITIVES

    assert "function_word_distribution_top50" in _ES_DISABLED_PRIMITIVES
    assert "character_ngram_simhash" in _ES_DISABLED_PRIMITIVES
    assert "pos_ngram_signature" in _ES_DISABLED_PRIMITIVES
    assert "optional_grammar_signature" in _ES_DISABLED_PRIMITIVES
