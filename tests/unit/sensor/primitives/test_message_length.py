"""Unit tests for message_length_class and message_length_variance_class."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.sensor.primitives.message_length import (
    MIN_MESSAGES,
    PRIMITIVE_NAME_CLASS,
    PRIMITIVE_NAME_VARIANCE,
    compute_class,
    compute_variance,
)

_TS = datetime(2026, 5, 1, tzinfo=UTC)


def _corpus_bodies(n: int, msg: str) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    corpus = [(_TS, UUID(f"00000000-0000-0000-0000-{i:012d}"), f"ref:{i}") for i in range(n)]
    bodies = {f"ref:{i}": msg for i in range(n)}
    return corpus, bodies


@pytest.mark.unit
def test_class_returns_none_below_min_messages() -> None:
    corpus, bodies = _corpus_bodies(MIN_MESSAGES - 1, "hello")
    assert compute_class(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_variance_returns_none_below_min_messages() -> None:
    corpus, bodies = _corpus_bodies(MIN_MESSAGES - 1, "hello")
    assert compute_variance(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_short_messages_bucket_short() -> None:
    # 3 words → "short" (1-5 words)
    corpus, bodies = _corpus_bodies(10, "hi how are")
    obs = compute_class(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "short"
    assert obs.primitive == PRIMITIVE_NAME_CLASS


@pytest.mark.unit
def test_medium_messages_bucket_medium() -> None:
    # 10 words → "medium" (6-20 words)
    corpus, bodies = _corpus_bodies(10, "this is a medium length message with about ten words")
    obs = compute_class(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "medium"


@pytest.mark.unit
def test_long_messages_bucket_long() -> None:
    # 30 words → "long" (21-50 words)
    corpus, bodies = _corpus_bodies(10, " ".join([f"word{i}" for i in range(30)]))
    obs = compute_class(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "long"


@pytest.mark.unit
def test_paragraph_messages_bucket_paragraph() -> None:
    # 60 words → "paragraph" (>50 words)
    corpus, bodies = _corpus_bodies(10, " ".join([f"word{i}" for i in range(60)]))
    obs = compute_class(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "paragraph"


@pytest.mark.unit
def test_uniform_messages_bucket_tight_variance() -> None:
    # All messages same length → CV≈0 → "tight"
    corpus, bodies = _corpus_bodies(10, "one two three four five")  # always 5 words
    obs = compute_variance(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "tight"
    assert obs.primitive == PRIMITIVE_NAME_VARIANCE


@pytest.mark.unit
def test_bimodal_messages_bucket_bimodal_variance() -> None:
    # Extreme skew: 11 one-word messages + 1 very long (200 words) → CV > 1.5 → "bimodal"
    n = 12
    corpus = [(_TS, UUID(f"00000000-0000-0000-0000-{i:012d}"), f"ref:{i}") for i in range(n)]
    short_msg = "hi"
    long_msg = " ".join([f"word{j}" for j in range(200)])
    bodies = {f"ref:{i}": long_msg if i == 11 else short_msg for i in range(n)}
    obs = compute_variance(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.value == "bimodal"


@pytest.mark.unit
def test_class_deterministic() -> None:
    corpus, bodies = _corpus_bodies(10, "hello world test")
    a = compute_class(corpus=corpus, bodies=bodies)
    b = compute_class(corpus=corpus, bodies=bodies)
    assert a is not None
    assert b is not None
    assert a.value == b.value


@pytest.mark.unit
def test_empty_bodies_returns_none() -> None:
    corpus, _ = _corpus_bodies(10, "hello")
    assert compute_class(corpus=corpus, bodies={}) is None
