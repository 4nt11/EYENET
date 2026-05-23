"""Shared fixtures for the calibration test suite.

Loads the committed baseline artifact once per session. Tests in this
directory assert against the artifact rather than recomputing from the
corpus (which is gitignored and not available in CI by default). Pass
``EYENET_RECALIBRATE=1`` to a future grid runner to regenerate the
artifact; otherwise these tests check the *committed* numbers haven't
drifted in the code that produces them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.calibration.artifact import CalibrationArtifact, load

BASELINE_PATH = Path("tests/fixtures/calibration/rutify_calibration_baseline.json")


@pytest.fixture(scope="session")
def baseline() -> CalibrationArtifact:
    """Session-scoped baseline artifact (loaded once)."""
    artifact, stored_hash = load(BASELINE_PATH)
    # Self-hash integrity check: any edit to the committed file without
    # recomputing the hash fails here before any test runs.
    computed = artifact.compute_self_hash()
    if computed != stored_hash:
        msg = (
            f"baseline artifact self_hash mismatch:\n"
            f"  stored:   {stored_hash}\n"
            f"  computed: {computed}\n"
            f"Re-run the calibration grid to regenerate {BASELINE_PATH}."
        )
        raise RuntimeError(msg)
    return artifact
