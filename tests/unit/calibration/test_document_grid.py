"""document_grid.run(): offline replay scoring of the tier pipeline.

Pure — real in-process ruleset + PII map (no jail), synthetic samples + captured
findings. Covers the headline under-classification metric, the metadata
escalate-only floor, the density sweep + §0 operating-point recommendation, the
confusion matrix, and the per-rule firing table.
"""

from __future__ import annotations

import pytest

from eyenet.calibration.document_corpus import DocumentSample
from eyenet.calibration.document_grid import meta_text, run
from eyenet.classifier.presidio import PiiFinding, load_pii_map
from eyenet.classifier.ruleset import load_ruleset
from eyenet.contracts.enums import SensitivityTier

pytestmark = pytest.mark.unit

N = SensitivityTier.NORMAL
R = SensitivityTier.RESTRICTED
C = SensitivityTier.CLASSIFIED

# Empirically-verified trigger strings (see slice-9 planning probe).
_TOP_SECRET = "TOP SECRET//NOFORN\nOperation details follow."
_BENIGN = "a friendly note about lunch plans on friday"


def _persons(n: int) -> tuple[PiiFinding, ...]:
    """n distinct high-confidence PERSON findings (drive the density floor)."""
    return tuple(
        PiiFinding(
            entity_type="PERSON",
            start=i * 10,
            end=i * 10 + 5,
            score=0.9,
            language="en",
            text=f"Name{i}",
        )
        for i in range(n)
    )


@pytest.fixture
def ruleset():
    return load_ruleset()


@pytest.fixture
def pii_map():
    return load_pii_map()


def test_meta_text_flattens_keys_and_string_leaves() -> None:
    out = meta_text({"a": "hello", "b": {"c": "world"}, "d": ["x", 5, None], "n": 3})
    parts = out.split("\n")
    assert "hello" in parts
    assert "world" in parts
    assert "x" in parts
    assert "5" not in parts  # numbers carry no markings → skipped
    assert "a" in parts and "b" in parts  # keys included


def test_zero_under_classification_on_correct_corpus(ruleset, pii_map) -> None:
    samples = [
        DocumentSample(doc_id="n1", expected_tier=N, text=_BENIGN),
        DocumentSample(doc_id="c1", expected_tier=C, text=_TOP_SECRET),
        DocumentSample(doc_id="r1", expected_tier=R, text="staff roster"),
    ]
    findings = {"r1": _persons(6)}  # 6 distinct PII → RESTRICTED at default density
    res = run(samples, findings, ruleset=ruleset, pii_map=pii_map)
    assert res.n_samples == 3
    assert res.under_classification_rate == 0.0
    by_id = {o.doc_id: o for o in res.outcomes}
    assert by_id["n1"].predicted is N
    assert by_id["c1"].predicted is C
    assert by_id["r1"].predicted is R
    assert by_id["r1"].presidio_floor is R


def test_metadata_banner_escalates_empty_body(ruleset, pii_map) -> None:
    # The §0 gap: empty extracted body, banner hidden in XMP keywords.
    samples = [
        DocumentSample(
            doc_id="m1",
            expected_tier=C,
            text="",
            embedded_meta={"xmp_keywords": _TOP_SECRET},
        )
    ]
    res = run(samples, {}, ruleset=ruleset, pii_map=pii_map)
    out = res.outcomes[0]
    assert out.predicted is C
    assert out.metadata_floor is C
    assert out.regex_floor is N  # body was empty
    assert res.under_classification_rate == 0.0


def test_detects_under_classification(ruleset, pii_map) -> None:
    # A doc the operator labeled CLASSIFIED but that carries no detectable signal
    # → the pipeline scores it NORMAL → the headline metric must catch it.
    samples = [DocumentSample(doc_id="miss", expected_tier=C, text=_BENIGN)]
    res = run(samples, {}, ruleset=ruleset, pii_map=pii_map)
    assert res.under_classification_rate == 1.0
    assert res.outcomes[0].under_classified is True
    assert res.outcomes[0].over_classified is False


def test_over_classification_is_counted_not_fatal(ruleset, pii_map) -> None:
    # A benign doc that happens to trip a banner is over-classified — recoverable.
    samples = [DocumentSample(doc_id="over", expected_tier=N, text=_TOP_SECRET)]
    res = run(samples, {}, ruleset=ruleset, pii_map=pii_map)
    assert res.under_classification_rate == 0.0
    assert res.over_classification_rate == 1.0
    assert res.outcomes[0].over_classified is True


def test_density_sweep_and_recommendation(ruleset, pii_map) -> None:
    samples = [
        DocumentSample(doc_id="n1", expected_tier=N, text=_BENIGN),
        DocumentSample(doc_id="r1", expected_tier=R, text="roster"),
    ]
    findings = {"r1": _persons(6)}
    res = run(samples, findings, ruleset=ruleset, pii_map=pii_map)
    assert res.density_sweep  # non-empty
    # every swept row has restricted < classified
    assert all(row.restricted_at < row.classified_at for row in res.density_sweep)
    # the recommendation minimizes under-classification first
    rec = next(
        row
        for row in res.density_sweep
        if row.restricted_at == res.recommended_restricted_at
        and row.classified_at == res.recommended_classified_at
    )
    assert rec.under_rate == min(row.under_rate for row in res.density_sweep)


def test_rule_firing_table_splits_by_label(ruleset, pii_map) -> None:
    samples = [
        DocumentSample(doc_id="c1", expected_tier=C, text=_TOP_SECRET),
        DocumentSample(doc_id="n1", expected_tier=N, text=_BENIGN),
    ]
    res = run(samples, {}, ruleset=ruleset, pii_map=pii_map)
    firing = {f.rule_name: f for f in res.rule_firing}
    assert "banner_en" in firing
    assert firing["banner_en"].on_elevated == 1
    assert firing["banner_en"].on_normal == 0  # fired only on the CLASSIFIED doc


def test_confusion_counts_sum_to_n(ruleset, pii_map) -> None:
    samples = [
        DocumentSample(doc_id="n1", expected_tier=N, text=_BENIGN),
        DocumentSample(doc_id="c1", expected_tier=C, text=_TOP_SECRET),
    ]
    res = run(samples, {}, ruleset=ruleset, pii_map=pii_map)
    assert sum(cell.count for cell in res.confusion) == res.n_samples
