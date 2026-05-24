"""General Impostors verifier — score separates same-author from different-author."""

from __future__ import annotations

import pytest

from eyenet.verifier.verifiers.general_impostors import GeneralImpostors


def _spanish_chat_a() -> list[str]:
    return ["hola que tal compita", "todo bien por aca", "mira esto que mira"] * 30


def _spanish_chat_b() -> list[str]:
    return ["hola compita que tal", "bien por aca todo", "esto mira que mira"] * 30


def _english_chat() -> list[str]:
    return ["how are you today", "looking good thanks", "see you later mate"] * 30


def _impostor_pool() -> list[list[str]]:
    return [
        ["hello world this is impostor one"] * 30,
        ["another impostor speaks here"] * 30,
        ["yet another distinct voice"] * 30,
    ]


@pytest.mark.unit
def test_same_author_scores_higher_than_diff_author() -> None:
    gi = GeneralImpostors(impostor_corpora=_impostor_pool(), n_iters=50, seed=1)
    same = gi.verify(_spanish_chat_a(), _spanish_chat_b(), language="es")
    diff = gi.verify(_spanish_chat_a(), _english_chat(), language="es")
    assert same.skipped is False
    assert diff.skipped is False
    assert same.score > diff.score


@pytest.mark.unit
def test_no_impostor_pool_degrades_with_low_confidence() -> None:
    gi = GeneralImpostors(impostor_corpora=[], n_iters=10, seed=1)
    r = gi.verify(_spanish_chat_a(), _spanish_chat_b(), language="es")
    assert r.skipped is False
    assert r.confidence < 0.5  # degraded path
    assert r.evidence.get("degraded_to") == "plain_cosine"


@pytest.mark.unit
def test_short_corpus_skipped() -> None:
    gi = GeneralImpostors(impostor_corpora=_impostor_pool(), n_iters=10, seed=1)
    r = gi.verify(["short"] * 2, _spanish_chat_b(), language="es")
    assert r.skipped is True
    assert r.skip_reason == "corpus_too_short"


@pytest.mark.unit
def test_deterministic_given_seed() -> None:
    p = _impostor_pool()
    a = GeneralImpostors(impostor_corpora=p, n_iters=20, seed=42).verify(
        _spanish_chat_a(), _spanish_chat_b(), language="es"
    )
    b = GeneralImpostors(impostor_corpora=p, n_iters=20, seed=42).verify(
        _spanish_chat_a(), _spanish_chat_b(), language="es"
    )
    assert a.score == b.score
