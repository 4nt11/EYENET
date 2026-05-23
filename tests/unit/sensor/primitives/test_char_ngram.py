"""Unit tests for character_ngram_simhash."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.sensor.primitives.character_ngram_simhash import PRIMITIVE_NAME, compute

_TS = datetime(2026, 5, 1, tzinfo=UTC)
_MID = UUID("00000000-0000-0000-0000-000000000001")

_LONG_EN = "the quick brown fox jumps over the lazy dog " * 30  # 360 tokens


def _corpus_from_body(
    body: str, n: int = 1
) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    corpus = [(_TS, _MID, f"ref:{i}") for i in range(n)]
    bodies = {f"ref:{i}": body for i in range(n)}
    return corpus, bodies


@pytest.mark.unit
def test_returns_none_below_min_tokens() -> None:
    corpus, bodies = _corpus_from_body("hi there")
    assert compute(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_returns_hex_hash_for_sufficient_corpus() -> None:
    corpus, bodies = _corpus_from_body(_LONG_EN)
    obs = compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.primitive == PRIMITIVE_NAME
    assert isinstance(obs.value, str)
    assert len(obs.value) == 16
    assert all(c in "0123456789abcdef" for c in obs.value)


@pytest.mark.unit
def test_deterministic_across_calls() -> None:
    corpus, bodies = _corpus_from_body(_LONG_EN)
    a = compute(corpus=corpus, bodies=bodies)
    b = compute(corpus=corpus, bodies=bodies)
    assert a is not None
    assert b is not None
    assert a.value == b.value


@pytest.mark.unit
def test_different_text_different_hash() -> None:
    corpus_a, bodies_a = _corpus_from_body(_LONG_EN)
    corpus_b, bodies_b = _corpus_from_body(
        "en un lugar de la mancha de cuyo nombre no quiero acordarme " * 30
    )
    obs_a = compute(corpus=corpus_a, bodies=bodies_a)
    obs_b = compute(corpus=corpus_b, bodies=bodies_b)
    assert obs_a is not None
    assert obs_b is not None
    assert obs_a.value != obs_b.value
