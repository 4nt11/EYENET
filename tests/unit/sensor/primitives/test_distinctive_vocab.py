"""Unit tests for distinctive_vocabulary_signature."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.sensor.primitives.distinctive_vocabulary_signature import (
    MIN_MESSAGES,
    PRIMITIVE_NAME,
    compute,
)

_TS = datetime(2026, 5, 1, tzinfo=UTC)
_MID = UUID("00000000-0000-0000-0000-000000000001")


def _corpus(
    n: int, body_fn: Callable[[int], str] | None = None
) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    if body_fn is None:

        def body_fn(i: int) -> str:
            return f"distinctive word{i} unique token{i} rare lexeme{i} special phrase{i}"

    corpus = [(_TS, _MID, f"ref:{i}") for i in range(n)]
    bodies = {f"ref:{i}": body_fn(i) for i in range(n)}
    return corpus, bodies


@pytest.mark.unit
def test_returns_none_below_min_messages() -> None:
    corpus, bodies = _corpus(MIN_MESSAGES - 1)
    assert compute(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_returns_observation_with_sufficient_corpus() -> None:
    corpus, bodies = _corpus(MIN_MESSAGES)
    obs = compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.primitive == PRIMITIVE_NAME
    assert len(obs.value) == 16


@pytest.mark.unit
def test_deterministic() -> None:
    corpus, bodies = _corpus(MIN_MESSAGES)
    a = compute(corpus=corpus, bodies=bodies)
    b = compute(corpus=corpus, bodies=bodies)
    assert a is not None
    assert b is not None
    assert a.value == b.value


@pytest.mark.unit
def test_different_vocabularies_different_hashes() -> None:
    corpus_a, bodies_a = _corpus(MIN_MESSAGES, lambda i: f"english word unique special rare{i}")
    corpus_b, bodies_b = _corpus(MIN_MESSAGES, lambda i: f"español palabra única especial rara{i}")
    obs_a = compute(corpus=corpus_a, bodies=bodies_a)
    obs_b = compute(corpus=corpus_b, bodies=bodies_b)
    assert obs_a is not None
    assert obs_b is not None
    assert obs_a.value != obs_b.value
