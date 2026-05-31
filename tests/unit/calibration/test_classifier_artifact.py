"""classifier_artifact build/write/load/verify + an always-on under-class guard.

Two concerns, both pure + offline (no jail — the seed findings are committed):

* the artifact machinery: round-trip, self_hash integrity, tamper detection;
* a LIVE-pipeline guard: re-run the document grid over the COMMITTED seed corpus
  and assert the headline under-classification rate is still ZERO. Unlike the
  ``@pytest.mark.calibration`` regression (which checks the committed numbers),
  this runs in the default suite so a pipeline change that starts
  under-classifying a seed document fails CI immediately (§0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eyenet.calibration import classifier_artifact, document_grid
from eyenet.calibration.document_corpus import load_document_corpus, load_findings, sha256_file
from eyenet.classifier.presidio import load_pii_map
from eyenet.classifier.ruleset import load_ruleset

pytestmark = pytest.mark.unit

_FIXTURES = Path("tests/fixtures/calibration")
_CORPUS = _FIXTURES / "classifier_seed_corpus.jsonl"
_FINDINGS = _FIXTURES / "classifier_seed_findings.jsonl"


def _build_grid() -> document_grid.DocumentGridResult:
    samples = load_document_corpus(_CORPUS)
    findings = load_findings(_FINDINGS)
    return document_grid.run(samples, findings, ruleset=load_ruleset(), pii_map=load_pii_map())


def test_no_new_under_classification() -> None:
    # The always-on §0 no-regression guard: re-run the LIVE pipeline over the
    # committed corpus and assert the under-classified set has not GROWN beyond
    # the committed allowlist. A code change that starts under-classifying a doc
    # that was previously correct fails CI immediately. (The two committed gaps —
    # doc_008 OCR banner, doc_022 informal chat — are the LLM-tripwire's domain.)
    committed = classifier_artifact.verify(
        Path("tests/fixtures/calibration/classifier_calibration_baseline.json")
    )
    allowed = set(committed["under_classified_doc_ids"])
    grid = _build_grid()
    live_under = {o.doc_id for o in grid.outcomes if o.under_classified}
    new_under = live_under - allowed
    assert not new_under, f"NEW under-classifications (regression): {sorted(new_under)}"


def test_build_write_load_round_trip(tmp_path: Path) -> None:
    grid = _build_grid()
    art = classifier_artifact.build(
        grid,
        corpus_id="t",
        corpus_sha256=sha256_file(_CORPUS),
        n_finding_docs=grid.n_samples,
        labeler="tester",
    )
    out = tmp_path / "artifact.json"
    stored = classifier_artifact.write(art, out)
    assert stored == art.compute_self_hash()
    payload = classifier_artifact.verify(out)  # raises on mismatch
    assert payload["corpus_id"] == "t"
    # the under-classified set round-trips as a list of doc_ids
    assert set(payload["under_classified_doc_ids"]) == {
        o.doc_id for o in grid.outcomes if o.under_classified
    }


def test_verify_detects_tampering(tmp_path: Path) -> None:
    grid = _build_grid()
    art = classifier_artifact.build(
        grid, corpus_id="t", corpus_sha256="x", n_finding_docs=0, labeler="t"
    )
    out = tmp_path / "artifact.json"
    classifier_artifact.write(art, out)
    # Tamper: flip the headline rate without recomputing the hash.
    raw = json.loads(out.read_text())
    raw["under_classification_rate"] = 0.5
    out.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="self_hash mismatch"):
        classifier_artifact.verify(out)


def test_canonical_hash_ignores_self_hash_key() -> None:
    body = {"a": 1, "b": "x"}
    h1 = classifier_artifact.canonical_self_hash(body)
    h2 = classifier_artifact.canonical_self_hash({**body, "self_hash": "anything"})
    assert h1 == h2
