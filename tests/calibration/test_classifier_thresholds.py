"""Regression test for the committed document-classifier calibration baseline.

Mirrors the Rutify/verifier baseline tests: loads the committed artifact, checks
its self_hash (any edit without recomputing the hash fails), and asserts the
load-bearing invariants.

The corpus is 50 real labelled docs (multilingual, adversarial) + 1 synthetic
metadata probe. The deterministic pipeline under-classifies exactly two
documented KNOWN-GAP cases (doc_008 OCR-mangled banner, doc_022 informal leaked
chat) — both the LLM-tripwire's domain by design (CLASSIFIER_PLAN §3). The gate
is therefore "no NEW document joins the under-classified set", not a hard zero:
``under_classified_doc_ids`` is the pinned allowlist.

``@pytest.mark.calibration`` so it is excluded from the default ``-m "unit or
contract"`` run. The always-on live-pipeline no-regression guard lives in
``tests/unit/calibration/test_classifier_artifact.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.calibration import classifier_artifact

pytestmark = pytest.mark.calibration

BASELINE_PATH = Path("tests/fixtures/calibration/classifier_calibration_baseline.json")

# The documented known-gap under-classifications (see the artifact notes):
KNOWN_UNDER: frozenset[str] = frozenset({"doc_008", "doc_022"})


@pytest.fixture(scope="session")
def payload() -> dict[str, object]:
    # verify() raises on a self_hash mismatch — the tamper-evidence gate.
    return classifier_artifact.verify(BASELINE_PATH)


def test_self_hash_and_schema(payload: dict[str, object]) -> None:
    assert payload["schema_version"] == classifier_artifact.ARTIFACT_SCHEMA_VERSION


def test_known_under_set_is_pinned(payload: dict[str, object]) -> None:
    # The §0 gate: the committed under-classified set is EXACTLY the two
    # documented LLM-backstop cases — no more.
    assert set(payload["under_classified_doc_ids"]) == KNOWN_UNDER


def test_recalibration_curbed_over_classification(payload: dict[str, object]) -> None:
    # v2 PII-map recalibration drove over-classification from 0.588 (v1) down;
    # guard against a regression back toward "classify everything".
    assert payload["over_classification_rate"] < 0.20
    assert payload["exact_match_rate"] > 0.75


def test_grid_provenance_versions(payload: dict[str, object]) -> None:
    grid = payload["grid"]
    assert isinstance(grid, dict)
    assert grid["ruleset_version"] == "v4"
    assert grid["map_version"] == "v2"


def test_metadata_gap_and_true_positives(payload: dict[str, object]) -> None:
    grid = payload["grid"]
    assert isinstance(grid, dict)
    by_id = {o["doc_id"]: o for o in grid["outcomes"]}
    # The §0 metadata gap: empty body + banner in XMP keywords → CLASSIFIED.
    assert by_id["syn_meta_banner"]["predicted"] == "classified"
    assert by_id["syn_meta_banner"]["metadata_floor"] == "classified"
    # A structural classification banner is a true positive.
    assert by_id["doc_005"]["predicted"] == "classified"
