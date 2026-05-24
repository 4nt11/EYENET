"""Verifier calibration grid — synthetic AUC + sweep + artifact roundtrip.

The committed Rutify baseline (``rutify_calibration_baseline.json``) was
generated before M8 and ships with ``verifiers=()``; an AUC budget against
that baseline lands once the operator regenerates the artifact with the
M8 verifier grid wired in. Until then this suite asserts on a synthetic
deterministic corpus so the calibration machinery itself is regression-
tested in CI.
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

import pytest

from eyenet.calibration.artifact import (
    _ES_DISABLED_VERIFIERS,
    ARTIFACT_SCHEMA_VERSION,
    CalibrationArtifact,
    build,
    load,
    write,
)
from eyenet.calibration.corpus import RutifyMessage
from eyenet.calibration.simhash_grid import GridResult
from eyenet.calibration.verifier_grid import (
    mann_whitney_auc_higher_better,
    run as run_verifier_grid,
)


def _synthetic_corpus(*, seed: int = 7) -> list[RutifyMessage]:
    """6 senders x 60 msgs, two style clusters - deterministic via seed."""
    rng = random.Random(seed)  # noqa: S311 — test fixture, not crypto
    msgs: list[RutifyMessage] = []
    pool_a = [
        "hola que tal compita todo bien",
        "muy bien gracias amigo mira esto",
        "che mira lo que pasa aca",
    ]
    pool_b = [
        "hello how are you doing today",
        "thanks for the message my friend",
        "see you later have a good one",
    ]
    for sid in range(1, 7):
        pool = pool_a if sid % 2 == 0 else pool_b
        for mid in range(60):
            msgs.append(
                RutifyMessage(
                    chat_id=1,
                    msg_id=sid * 1000 + mid,
                    sender_id=sid,
                    ts=float(sid * 100_000 + mid),
                    text=rng.choice(pool) + f" w{mid % 5}",
                    reply_to_msg_id=None,
                    forwarded_from_id=None,
                    mentions=(),
                )
            )
    return msgs


@pytest.mark.calibration
def test_mann_whitney_higher_better_perfect_separation() -> None:
    within = [0.9, 0.95, 0.85]
    cross = [0.1, 0.2, 0.05]
    assert mann_whitney_auc_higher_better(within, cross) == 1.0


@pytest.mark.calibration
def test_mann_whitney_higher_better_no_signal() -> None:
    # Identical distributions → 0.5 (all ties).
    assert mann_whitney_auc_higher_better([0.5, 0.5], [0.5, 0.5]) == 0.5


@pytest.mark.calibration
def test_verifier_grid_separates_synthetic_clusters() -> None:
    """Two-cluster synthetic corpus produces AUC above noise floor."""
    msgs = _synthetic_corpus()
    grid = run_verifier_grid(msgs, min_messages=30, language="es")
    assert grid.actor_count >= 2
    assert len(grid.per_verifier) >= 1
    # Synthetic clusters are strongly separable; AUC must clear 0.6.
    for v in grid.per_verifier:
        assert v.auc >= 0.6, f"verifier {v.verifier} AUC={v.auc} below synthetic-corpus floor"


@pytest.mark.calibration
def test_verifier_grid_emits_one_entry_per_verifier() -> None:
    msgs = _synthetic_corpus()
    grid = run_verifier_grid(msgs, min_messages=30, language="es")
    names = {v.verifier for v in grid.per_verifier}
    # Default registry ships GI + NCD
    assert "general_impostors" in names
    assert "compression_distance" in names


@pytest.mark.calibration
def test_artifact_carries_verifier_entries() -> None:
    msgs = _synthetic_corpus()
    grid = run_verifier_grid(msgs, min_messages=30, language="es")
    artifact = build(
        corpus_id="synth",
        corpus_sha256="0" * 64,
        actor_count_total=6,
        actor_count_simhash_qualifying=6,
        min_messages=30,
        labeler="test",
        label_counts={"normal": 6},
        simhash_grid=GridResult(actor_count=0, half_hashes=(), per_primitive=()),
        simhash_es_disabled=False,
        recipe_results=[],
        verifier_grid=grid,
        verifier_es_disabled=False,
    )
    assert artifact.schema_version == ARTIFACT_SCHEMA_VERSION
    assert artifact.schema_version == "1.1"
    assert len(artifact.verifiers) == len(grid.per_verifier)


@pytest.mark.calibration
def test_artifact_roundtrip_preserves_verifiers() -> None:
    msgs = _synthetic_corpus()
    grid = run_verifier_grid(msgs, min_messages=30, language="es")
    artifact = build(
        corpus_id="synth",
        corpus_sha256="0" * 64,
        actor_count_total=6,
        actor_count_simhash_qualifying=6,
        min_messages=30,
        labeler="test",
        label_counts={"normal": 6},
        simhash_grid=GridResult(actor_count=0, half_hashes=(), per_primitive=()),
        simhash_es_disabled=False,
        recipe_results=[],
        verifier_grid=grid,
        verifier_es_disabled=False,
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    try:
        stored_hash = write(artifact, path)
        loaded, h = load(path)
        assert h == stored_hash
        assert loaded.compute_self_hash() == stored_hash
        assert len(loaded.verifiers) == len(artifact.verifiers)
        # Field-level equality on the first verifier entry
        if artifact.verifiers:
            a = artifact.verifiers[0]
            b = loaded.verifiers[0]
            assert a.verifier == b.verifier
            assert a.auc == b.auc
            assert a.chosen_threshold == b.chosen_threshold
    finally:
        path.unlink()


@pytest.mark.calibration
def test_es_disabled_verifiers_policy_starts_empty() -> None:
    """M8 ships GI+NCD enabled for Spanish. Empty set is the M8 baseline."""
    assert frozenset() == _ES_DISABLED_VERIFIERS


@pytest.mark.calibration
def test_committed_baseline_loads_at_schema_1_1(baseline: CalibrationArtifact) -> None:
    """Migrated baseline carries the new verifiers field (empty tuple, M5/M6.5 era)."""
    assert baseline.schema_version == "1.1"
    assert baseline.verifiers == ()


@pytest.mark.calibration
def test_artifact_schema_bump_documented() -> None:
    """1.1 is the M8 bump; future bumps update both the constant and the docstring."""
    assert ARTIFACT_SCHEMA_VERSION == "1.1"
