"""Unit tests for conversation_initiation_rate primitive."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.sensor.primitives.conversation_initiation_rate import (
    MIN_MESSAGES,
    PRIMITIVE_NAME,
    compute,
    compute_async,
)

_TS = datetime(2026, 5, 1, tzinfo=UTC)


def _make_corpus_reply(
    n_total: int,
    n_initiations: int,
) -> list[tuple[datetime, UUID, str, UUID | None]]:
    """Build a corpus-with-reply list. First `n_initiations` rows have no reply."""
    parent_id = UUID("00000000-0000-0000-0000-000000000099")
    return [
        (
            _TS,
            UUID(f"00000000-0000-0000-0000-{i:012d}"),
            f"ref:{i}",
            None if i < n_initiations else parent_id,
        )
        for i in range(n_total)
    ]


@pytest.mark.unit
def test_sync_compute_always_returns_none() -> None:
    # Sync compute is a stub — always None per module docstring.
    corpus = [(_TS, UUID(f"00000000-0000-0000-0000-{i:012d}"), f"ref:{i}") for i in range(20)]
    assert compute(corpus=corpus, bodies={}) is None


@pytest.mark.unit
def test_async_returns_none_below_min_messages() -> None:
    corpus = _make_corpus_reply(MIN_MESSAGES - 1, 5)
    result = asyncio.run(compute_async(corpus_with_reply=corpus))
    assert result is None


@pytest.mark.unit
def test_async_all_initiations_rate_one() -> None:
    corpus = _make_corpus_reply(20, 20)  # all reply_to is None
    result = asyncio.run(compute_async(corpus_with_reply=corpus))
    assert result is not None
    assert result.primitive == PRIMITIVE_NAME
    assert float(result.value) == pytest.approx(1.0)


@pytest.mark.unit
def test_async_no_initiations_rate_zero() -> None:
    corpus = _make_corpus_reply(20, 0)  # all replies
    result = asyncio.run(compute_async(corpus_with_reply=corpus))
    assert result is not None
    assert float(result.value) == pytest.approx(0.0)


@pytest.mark.unit
def test_async_half_initiations_rate_half() -> None:
    corpus = _make_corpus_reply(20, 10)
    result = asyncio.run(compute_async(corpus_with_reply=corpus))
    assert result is not None
    assert float(result.value) == pytest.approx(0.5)


@pytest.mark.unit
def test_async_deterministic() -> None:
    corpus = _make_corpus_reply(20, 5)
    a = asyncio.run(compute_async(corpus_with_reply=corpus))
    b = asyncio.run(compute_async(corpus_with_reply=corpus))
    assert a is not None
    assert b is not None
    assert a.value == b.value
