"""Unit tests for function_word_distribution_top50."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.sensor.primitives.function_word_distribution_top50 import (
    MIN_MESSAGES,
    PRIMITIVE_NAME,
    compute,
)

_TS = datetime(2026, 5, 1, tzinfo=UTC)
_MID = UUID("00000000-0000-0000-0000-000000000001")

_EN_BODY = (
    "the quick brown fox jumps over the lazy dog and the cat sat on the mat "
    "with all the other animals in the forest where they can be at peace "
)
_ES_BODY = (
    "de la que el en y a los del se las un por con una su para es al lo "
    "como más pero sus le ya o fue este ha sí porque esta entre cuando muy "
)


def _corpus(n: int, body: str) -> tuple[list[tuple[datetime, UUID, str]], dict[str, str]]:
    corpus = [(_TS, _MID, f"ref:{i}") for i in range(n)]
    bodies = {f"ref:{i}": body for i in range(n)}
    return corpus, bodies


@pytest.mark.unit
def test_returns_none_below_min() -> None:
    # 5 messages, short body — neither 30-msg nor 500-token threshold met
    corpus, bodies = _corpus(5, "hi there friend")
    assert compute(corpus=corpus, bodies=bodies) is None


@pytest.mark.unit
def test_returns_observation_when_token_threshold_met() -> None:
    # Token count: 500 tokens from 5 messages of ~100 tokens each
    long_body = (_EN_BODY * 6)[:500]
    corpus, bodies = _corpus(5, long_body)
    obs = compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert obs.primitive == PRIMITIVE_NAME
    assert len(obs.value) == 16


@pytest.mark.unit
def test_returns_observation_when_message_threshold_met() -> None:
    corpus, bodies = _corpus(MIN_MESSAGES, _EN_BODY)
    obs = compute(corpus=corpus, bodies=bodies)
    assert obs is not None


@pytest.mark.unit
def test_deterministic() -> None:
    corpus, bodies = _corpus(MIN_MESSAGES, _EN_BODY)
    a = compute(corpus=corpus, bodies=bodies)
    b = compute(corpus=corpus, bodies=bodies)
    assert a is not None
    assert b is not None
    assert a.value == b.value


@pytest.mark.unit
def test_en_and_es_produce_different_hashes() -> None:
    corpus_en, bodies_en = _corpus(MIN_MESSAGES, _EN_BODY)
    corpus_es, bodies_es = _corpus(MIN_MESSAGES, _ES_BODY)
    obs_en = compute(corpus=corpus_en, bodies=bodies_en)
    obs_es = compute(corpus=corpus_es, bodies=bodies_es)
    assert obs_en is not None
    assert obs_es is not None
    assert obs_en.value != obs_es.value


@pytest.mark.unit
def test_source_label_contains_language() -> None:
    corpus, bodies = _corpus(MIN_MESSAGES, _EN_BODY)
    obs = compute(corpus=corpus, bodies=bodies)
    assert obs is not None
    assert "#en" in obs.source or "#es" in obs.source
