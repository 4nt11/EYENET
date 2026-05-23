"""Unit tests for MATTR (lexical.vocabulary_richness)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.sensor.primitives.mattr import PRIMITIVE_NAME, compute

_TS = datetime(2026, 5, 1, tzinfo=UTC)
_MID = UUID("00000000-0000-0000-0000-000000000001")


def _corpus(
    n: int, body: str = "the cat sat on the mat"
) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    corpus = [(_TS, _MID, f"ref:{i}") for i in range(n)]
    bodies = {f"ref:{i}": body for i in range(n)}
    return corpus, bodies


@pytest.mark.unit
def test_returns_none_below_min_tokens() -> None:
    # 5 short messages x 6 tokens = 30 tokens < MIN_TOKENS
    corpus, bodies = _corpus(5, "hi there")
    assert compute(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_returns_observation_with_sufficient_corpus() -> None:
    # 20 messages x 6 tokens = 120 tokens >= MIN_TOKENS (100)
    corpus, bodies = _corpus(20)
    obs = compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.primitive == PRIMITIVE_NAME
    assert 0.0 <= float(obs.value) <= 1.0


@pytest.mark.unit
def test_deterministic() -> None:
    corpus, bodies = _corpus(20)
    a = compute(corpus=corpus, bodies=bodies)
    b = compute(corpus=corpus, bodies=bodies)
    assert a is not None
    assert b is not None
    assert a.value == b.value


@pytest.mark.unit
def test_high_vocab_richness_higher_than_low() -> None:
    # Repeated words → low MATTR; unique words → high MATTR.
    corpus_rep, bodies_rep = _corpus(20, "the the the the the the")
    corpus_rich = [(_TS, _MID, f"ref:{i}") for i in range(20)]
    bodies_rich = {
        f"ref:{i}": f"word{i} token{i} unique{i} special{i} distinct{i} rare{i}" for i in range(20)
    }
    obs_rep = compute(corpus=corpus_rep, bodies=bodies_rep)
    obs_rich = compute(corpus=corpus_rich, bodies=bodies_rich)
    assert obs_rep is not None
    assert obs_rich is not None
    assert float(obs_rich.value) > float(obs_rep.value)


@pytest.mark.unit
def test_empty_bodies_returns_none() -> None:
    corpus = [(_TS, _MID, "ref:0")]
    bodies: dict[str, str] = {}
    assert compute(corpus=corpus, bodies=bodies) is None
