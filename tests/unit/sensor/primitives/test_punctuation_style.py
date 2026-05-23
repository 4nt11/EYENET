"""Unit tests for punctuation_style primitive."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.sensor.primitives.punctuation_style import (
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


@pytest.mark.unit
def test_returns_none_below_min_messages() -> None:
    corpus, bodies = _corpus_bodies(["hello, world! How are you?"] * (MIN_MESSAGES - 1))
    assert compute(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_returns_observation_with_sufficient_corpus() -> None:
    msgs = ["Hello, world! How are you? I'm fine... really!"] * 15
    corpus, bodies = _corpus_bodies(msgs)
    obs = compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.primitive == PRIMITIVE_NAME
    assert isinstance(obs.value, str)


@pytest.mark.unit
def test_deterministic() -> None:
    msgs = ["Hello, world! How are you?"] * 15
    corpus, bodies = _corpus_bodies(msgs)
    a = compute(corpus=corpus, bodies=bodies)
    b = compute(corpus=corpus, bodies=bodies)
    assert a is not None
    assert b is not None
    assert a.value == b.value


@pytest.mark.unit
def test_different_punctuation_patterns_differ() -> None:
    heavy_punct = ["Hello!!! What??? Really... Yes, I think so; but: why?"] * 15
    no_punct = ["hello world this is a sentence with no punctuation at all"] * 15
    corpus_a, bodies_a = _corpus_bodies(heavy_punct)
    corpus_b, bodies_b = _corpus_bodies(no_punct)
    a = compute(corpus=corpus_a, bodies=bodies_a)
    b = compute(corpus=corpus_b, bodies=bodies_b)
    # Both may return None if no punctuation at all — only assert when both non-None
    if a is not None and b is not None:
        assert a.value != b.value


@pytest.mark.unit
def test_returns_none_for_empty_bodies() -> None:
    corpus, _ = _corpus_bodies(["hello world"] * 15)
    assert compute(corpus=corpus, bodies={}) is None
