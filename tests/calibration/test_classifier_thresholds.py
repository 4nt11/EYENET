"""Regression test for the committed document-classifier calibration baseline.

Mirrors the Rutify/verifier baseline tests: loads the committed artifact, checks
its self_hash (any edit without recomputing the hash fails), and asserts the
load-bearing invariants — above all that the HEADLINE under-classification rate
is ZERO (a sensitive document scored NORMAL is the one catastrophic error, §0).

``@pytest.mark.calibration`` so it is excluded from the default ``-m "unit or
contract"`` run, like the other calibration regressions. The always-on
live-pipeline guard lives in ``tests/unit/calibration/test_classifier_artifact.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.calibration import classifier_artifact

pytestmark = pytest.mark.calibration

BASELINE_PATH = Path("tests/fixtures/calibration/classifier_calibration_baseline.json")


@pytest.fixture(scope="session")
def payload() -> dict[str, object]:
    # verify() raises on a self_hash mismatch — the tamper-evidence gate.
    return classifier_artifact.verify(BASELINE_PATH)


def test_self_hash_and_schema(payload: dict[str, object]) -> None:
    assert payload["schema_version"] == classifier_artifact.ARTIFACT_SCHEMA_VERSION


def test_headline_under_classification_is_zero(payload: dict[str, object]) -> None:
    # The §0 gate: no labeled-sensitive doc may score below its tier.
    assert payload["under_classification_rate"] == 0.0


def test_grid_provenance_versions(payload: dict[str, object]) -> None:
    grid = payload["grid"]
    assert isinstance(grid, dict)
    assert grid["ruleset_version"]  # non-empty
    assert grid["map_version"]


def test_fp_prone_and_metadata_gap_outcomes(payload: dict[str, object]) -> None:
    grid = payload["grid"]
    assert isinstance(grid, dict)
    outcomes = grid["outcomes"]
    assert isinstance(outcomes, list)
    by_id = {o["doc_id"]: o for o in outcomes}
    # CONFIDENTIAL in a prose footer must stay NORMAL (banner anchoring).
    assert by_id["n_confid_footer"]["predicted"] == "normal"
    # The §0 metadata gap: empty body + banner in XMP keywords → CLASSIFIED.
    assert by_id["c_meta_banner"]["predicted"] == "classified"
    assert by_id["c_meta_banner"]["metadata_floor"] == "classified"
    # Structural true positives.
    assert by_id["c_banner"]["predicted"] == "classified"
    assert by_id["c_privkey"]["predicted"] == "classified"


def test_no_confusion_cell_below_the_diagonal(payload: dict[str, object]) -> None:
    # Belt-and-suspenders for the headline: no (expected > predicted) cell.
    grid = payload["grid"]
    assert isinstance(grid, dict)
    order = {"normal": 0, "restricted": 1, "classified": 2}
    for cell in grid["confusion"]:
        assert order[cell["predicted"]] >= order[cell["expected"]], cell
