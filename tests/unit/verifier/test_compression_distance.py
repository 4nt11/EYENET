"""NCD verifier — same-author concat compresses better than diff-author concat."""

from __future__ import annotations

import pytest

from eyenet.verifier.verifiers.compression_distance import CompressionDistance


@pytest.mark.unit
def test_same_author_scores_above_diff_author() -> None:
    ncd = CompressionDistance()
    same_a = ["hola que tal compita todo bien"] * 20
    same_b = ["hola que tal compita todo bien"] * 20
    diff_a = ["hello world how are you today"] * 20
    diff_b = ["bonjour le monde comment ça va"] * 20
    s = ncd.verify(same_a, same_b, language=None)
    d = ncd.verify(diff_a, diff_b, language=None)
    assert s.skipped is False
    assert d.skipped is False
    assert s.score > d.score


@pytest.mark.unit
def test_short_corpus_skipped() -> None:
    ncd = CompressionDistance()
    r = ncd.verify(["short"] * 2, ["long text here"] * 20, language=None)
    assert r.skipped is True


@pytest.mark.unit
def test_symmetry_under_arg_swap() -> None:
    """NCD's compressed-concat order is normalized; swapping A/B yields same score."""
    ncd = CompressionDistance()
    a = ["hola que tal compita"] * 20
    b = ["hello world how are you"] * 20
    r1 = ncd.verify(a, b, language=None)
    r2 = ncd.verify(b, a, language=None)
    assert r1.score == r2.score


@pytest.mark.unit
def test_score_clamped_to_unit_interval() -> None:
    ncd = CompressionDistance()
    a = ["x"] * 20
    b = ["y"] * 20
    r = ncd.verify(a, b, language=None)
    assert 0.0 <= r.score <= 1.0
