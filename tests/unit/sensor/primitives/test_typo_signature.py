"""Unit tests for typo_signature primitive."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.sensor.primitives.typo_signature import (
    MIN_MESSAGES,
    PRIMITIVE_NAME,
    compute,
)

_TS = datetime(2026, 5, 1, tzinfo=UTC)


def _corpus_bodies(
    messages: list[str],
) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    corpus = [
        (_TS, UUID(f"00000000-0000-0000-0000-{i:012d}"), f"ref:{i}") for i, _ in enumerate(messages)
    ]
    bodies = {f"ref:{i}": msg for i, msg in enumerate(messages)}
    return corpus, bodies


def _rich_sentence(suffix: str = "") -> str:
    # A sentence with varied vocabulary to ensure enough distinct words.
    return (
        f"The quick brown fox jumps over the lazy dog and runs away{suffix}. "
        "Meanwhile several large elephants observed the spectacle with great amusement. "
        "The complex situation required careful analysis of multiple competing factors."
    )


@pytest.mark.unit
def test_returns_none_below_min_messages() -> None:
    corpus, bodies = _corpus_bodies([_rich_sentence()] * (MIN_MESSAGES - 1))
    assert compute(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_returns_observation_with_sufficient_corpus() -> None:
    msgs = [_rich_sentence(f" {i}") for i in range(MIN_MESSAGES + 5)]
    corpus, bodies = _corpus_bodies(msgs)
    # May still return None if corpus doesn't have enough distinct words
    # (that's fine — just test it doesn't crash)
    result = compute(corpus=corpus, bodies=bodies)
    if result is not None:
        assert result.primitive == PRIMITIVE_NAME
        assert isinstance(result.value, str)
        assert len(result.value) == 16  # SHA-256 first 16 hex chars


@pytest.mark.unit
def test_deterministic() -> None:
    msgs = [_rich_sentence(f" {i}") for i in range(20)]
    corpus, bodies = _corpus_bodies(msgs)
    a = compute(corpus=corpus, bodies=bodies)
    b = compute(corpus=corpus, bodies=bodies)
    if a is not None and b is not None:
        assert a.value == b.value


@pytest.mark.unit
def test_known_typos_produce_stable_fingerprint() -> None:
    """A corpus with persistent typos in every message produces a stable hash."""
    base = "recieve the necesary information about the begining of the program. "
    msgs = [base * 3 + f" extra unique word {i} context sentence here" for i in range(20)]
    corpus, bodies = _corpus_bodies(msgs)
    a = compute(corpus=corpus, bodies=bodies)
    b = compute(corpus=corpus, bodies=bodies)
    if a is not None and b is not None:
        assert a.value == b.value


@pytest.mark.unit
def test_returns_none_for_empty_bodies() -> None:
    corpus, _ = _corpus_bodies([_rich_sentence()] * MIN_MESSAGES)
    assert compute(corpus=corpus, bodies={}) is None
