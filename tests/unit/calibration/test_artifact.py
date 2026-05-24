"""Unit tests for :mod:`eyenet.calibration.artifact`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eyenet.calibration.artifact import (
    ARTIFACT_SCHEMA_VERSION,
    CalibrationArtifact,
    RecipeArtifactEntry,
    SimhashArtifactEntry,
    load,
    write,
)


def _make_artifact() -> CalibrationArtifact:
    sh = SimhashArtifactEntry(
        primitive="function_word_distribution_top50",
        language="es",
        enabled=False,
        actors_fired=59,
        within_count=59,
        within_min=2,
        within_p50=9,
        within_max=25,
        cross_count=1711,
        cross_min=0,
        cross_p50=9,
        cross_max=33,
        auc=0.5546,
        strategy="precision_floor:0.70",
        chosen_threshold=None,
        chosen_precision=0.0,
        chosen_recall=0.0,
        chosen_f1=0.0,
        f1_max_threshold=5,
        f1_max_f1=0.086,
    )
    rc = RecipeArtifactEntry(
        name="bot_or_automated_poster",
        version="0.2",
        positive_label="bot",
        strategy="operator_locked",
        axes=(
            {
                "axes": [
                    {"feature": "init_rate", "op": ">=", "value": 0.95},
                    {"feature": "length_cv", "op": "<=", "value": 0.30},
                ]
            },
        ),
        groups_count=1,
        tp=1,
        fp=0,
        tn=73,
        fn=0,
        precision=1.0,
        recall=1.0,
        f1=1.0,
        notes=("test entry",),
    )
    return CalibrationArtifact(
        schema_version=ARTIFACT_SCHEMA_VERSION,
        corpus_id="test-corpus",
        corpus_sha256="0" * 64,
        eyenet_version="0.0.1",
        behave_text_version="0.0.1",
        generated_at="2026-05-22T12:00:00Z",
        actor_count_total=74,
        actor_count_simhash_qualifying=73,
        min_messages=50,
        labeler="test",
        label_counts={"bot": 1, "normal": 46},
        simhash=(sh,),
        recipes=(rc,),
        notes=("test note",),
    )


@pytest.mark.unit
def test_artifact_self_hash_is_deterministic() -> None:
    a = _make_artifact()
    h1 = a.compute_self_hash()
    h2 = a.compute_self_hash()
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


@pytest.mark.unit
def test_artifact_self_hash_changes_when_field_changes() -> None:
    a = _make_artifact()
    h1 = a.compute_self_hash()
    b = CalibrationArtifact(**{**a.__dict__, "actor_count_total": 99})
    h2 = b.compute_self_hash()
    assert h1 != h2


@pytest.mark.unit
def test_artifact_round_trip(tmp_path: Path) -> None:
    a = _make_artifact()
    out = tmp_path / "artifact.json"
    stored_hash = write(a, out)
    loaded, loaded_hash = load(out)
    assert loaded_hash == stored_hash
    # Recomputed hash matches what was stored
    assert loaded.compute_self_hash() == stored_hash
    # Field-level equality
    assert loaded.corpus_id == a.corpus_id
    assert loaded.simhash == a.simhash
    assert loaded.recipes == a.recipes


@pytest.mark.unit
def test_baseline_artifact_loads_and_verifies() -> None:
    """The committed Rutify baseline must load cleanly + pass its own hash."""
    p = Path("tests/fixtures/calibration/rutify_calibration_baseline.json")
    artifact, stored_hash = load(p)
    assert artifact.schema_version == ARTIFACT_SCHEMA_VERSION
    assert artifact.compute_self_hash() == stored_hash


@pytest.mark.unit
def test_baseline_artifact_has_expected_shape() -> None:
    """The committed Rutify baseline carries the structure tests rely on."""
    p = Path("tests/fixtures/calibration/rutify_calibration_baseline.json")
    artifact, _ = load(p)
    assert artifact.corpus_id == "rutify-full-2026-05-02"
    # 4 simhashes after M6.5: function_word + char_ngram + pos_ngram + optional_grammar.
    # All four disabled for ES per operator policy (calibration 2026-05-23).
    assert len(artifact.simhash) == 4
    assert all(not s.enabled for s in artifact.simhash)  # all es disabled
    recipe_names = {r.name for r in artifact.recipes}
    assert recipe_names == {"lurker_or_observer", "bot_or_automated_poster", "chatty_member"}


@pytest.mark.unit
def test_committed_artifact_is_pretty_printed() -> None:
    """Sanity check: artifact is human-readable JSON, not minified."""
    raw = Path("tests/fixtures/calibration/rutify_calibration_baseline.json").read_text()
    # Indented JSON has newlines and 2-space indents.
    assert "\n  " in raw
    parsed = json.loads(raw)
    assert "self_hash" in parsed
